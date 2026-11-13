"""The game as a web page: a small HTTP server, and the loop that carries out what the page asks for.

Runs under both Python (on a laptop) and MicroPython (on the ESP32).
"""
import _thread
import json
import os
import time

import chess

from .game import Game, Graveyard
from .geometry import Geometry
from .grid import GRID_HELP, parse_command
from .machine import FakeMachine, MachineError
from .mover import Mover
from .server import read_request, respond, serve
from .session import GridSession

PAGE_PATH = __file__.rsplit("/", 1)[0] + "/page.html"
ASSETS_PATH = __file__.rsplit("/", 1)[0] + "/assets/"
ASSET_TYPES = {"jpg": "image/jpeg", "webp": "image/webp", "png": "image/png", "svg": "image/svg+xml"}
LOG_LENGTH = 40
SUGGESTED_ACCELERATION = 500
HIGH_ACCELERATION = 1000
MOVING_COMMANDS = ("move", "goto", "park", "outline")
# How many moves may wait behind the one being carried out.
MOST_WAITING = 4
OUTLINE_CORNERS = ("a1", "a8", "h8", "h1")


class App:
    """One game, driven by commands that arrive from the web page.

    Commands run one at a time on the thread that calls run(); the web
    server's thread only hands them over, reads the state and asks for a stop.

    Moves can be handed over while earlier moves are still being carried
    out. They wait in a queue, and each is checked on arrival against the
    position it will meet, which is kept in plan: a second game whose board
    runs ahead of the real one by the moves not yet finished.
    """

    def __init__(self, cfg, machine, state_path=None, sounds=None, magnet_sensor=None):
        """state_path names a file that keeps the grid across restarts of this program.

        sounds plays the game's sounds (see sound.py); without it the game is silent.
        magnet_sensor() tells whether the board's sensor feels a magnet right now.
        """
        mover = Mover(
            machine, Geometry.from_config(cfg["board"]), cfg["travel_feed"], cfg["drag_feed"],
            centring_mm=cfg.get("centring_mm", 0.0),
        )
        graveyard = cfg.get("graveyard")
        game = Game(
            mover,
            Graveyard.from_config(graveyard) if graveyard else None,
            remove_by_hand=lambda name: self.ask("Take the captured piece off %s by hand." % name.upper()),
        )
        self.cfg = cfg
        self.machine = machine
        self.session = GridSession(game, cfg.get("slow_feed", 1500), self.ask, sounds)
        self.sounds = self.session.sounds
        self.magnet_sensor = magnet_sensor
        self.voice = None
        self.lock = _thread.allocate_lock()
        self.queue = []
        self.only_moves = False
        self.plan = None
        self.planned = None
        self.failed = False
        self.busy = True
        self.ready = False
        self.stopping = False
        self.question = None
        self.answer = None
        self.log = []
        self.log_count = 0
        self.status = ""
        self.moves = {}
        self.state_path = state_path
        self._load()
        self._refresh()

    def say(self, text, error=False):
        self.log_count += 1
        self.log = (self.log + [{"n": self.log_count, "text": text, "error": error}])[-LOG_LENGTH:]

    def ask(self, message, yes="Done", no="Cancel"):
        """Show the players a question and wait for their answer; a stop counts as no."""
        self.answer = None
        self.question = {"text": message, "yes": yes, "no": no}
        while self.answer is None and not self.stopping:
            self.machine.idle()
            self.sounds.service()
            time.sleep(0.05)
        self.question = None
        return self.answer is True

    def give_answer(self, yes):
        if self.question is not None:
            self.answer = bool(yes)

    def submit(self, text):
        """Queue a typed command. Returns (accepted, message for the player)."""
        text = text.strip()
        if text.lower() in ("reconnect", "outline"):
            command = (text.lower(),)
        else:
            try:
                command = parse_command(text)
            except ValueError as e:
                return False, str(e)
            if command[0] == "grid":
                return True, ""
            if command[0] == "help":
                return True, GRID_HELP
            if command[0] == "quit":
                command = ("park",)
        is_move = command[0] == "move"
        with self.lock:
            idle = not self.busy and not self.queue
            if not idle and not (is_move and self.only_moves and not self.stopping):
                return False, "The board is still busy with the last command."
            if len(self.queue) >= MOST_WAITING:
                return False, "%d moves are already waiting. Let the board catch up first." % MOST_WAITING
            if is_move and self.session.rules and self.ready:
                game = self.session.game
                if self.plan is None:
                    plan = Game(game.mover)
                    plan.board = chess.Board(game.board.fen())
                else:
                    plan = self.plan
                try:
                    move = plan.move_between(command[1], command[2], command[3])
                except ValueError as e:
                    if not idle:
                        return False, str(e)
                    # With nothing ahead of it, the move is refused where it is carried out.
                    move = None
                if move is not None:
                    plan.board.push(move)
                    self.plan = plan
                    status, moves = self._describe(plan, "White" if plan.board.turn else "Black")
                    self.planned = {
                        "pieces": {chess.square_name(sq): p.symbol() for sq, p in plan.board.piece_map().items()},
                        "status": status, "moves": moves,
                    }
            if idle:
                self.only_moves = is_move
            self.queue.append(command)
            self.busy = True
        return True, ""

    @property
    def pending(self):
        """The next command waiting to be carried out, or None."""
        queue = self.queue
        return queue[0] if queue else None

    def stop(self):
        """Halt whatever the engraver is doing. Called from the web server's thread."""
        if not self.busy:
            return False, "Nothing is moving."
        self.stopping = True
        self.failed = True
        self.machine.interrupt()
        return True, ""

    def state(self):
        game = self.session.game
        head = self.machine.head
        parked = {"white": "", "black": ""}
        if game.graveyard is not None:
            for color in parked:
                parked[color] = "".join(piece.symbol() for _, piece in game.graveyard.parked[color])
        felt = None if self.magnet_sensor is None else self.magnet_sensor()
        planned = self.planned
        return {
            "pieces": planned["pieces"] if planned else {
                chess.square_name(sq): p.symbol() for sq, p in game.board.piece_map().items()
            },
            "parked": parked,
            "head": None if head is None else game.mover.geometry.square_at(head),
            "came_from": self.session.came_from,
            "rules": self.session.rules,
            "status": planned["status"] if planned else self.status,
            "moves": planned["moves"] if planned else self.moves,
            "busy": self.busy,
            "waiting": len(self.queue),
            "ready": self.ready,
            "question": self.question,
            "sensor": None if felt is None else bool(felt),
            "voice": None if self.voice is None else self.voice.state(),
            "centring": game.mover.centring_mm,
            "log": self.log,
        }

    def _save(self):
        if self.state_path is None:
            return
        game = self.session.game
        parked = []
        if game.graveyard is not None:
            for color in ("white", "black"):
                parked += [[slot[0], slot[1], piece.symbol()] for slot, piece in game.graveyard.parked[color]]
        saved = {"fen": game.board.fen(), "parked": parked, "rules": self.session.rules}
        try:
            with open(self.state_path + ".new", "w") as f:
                json.dump(saved, f)
            os.rename(self.state_path + ".new", self.state_path)
        except OSError as e:
            self.say("The grid could not be saved (%s); it will be forgotten at the next restart." % e, error=True)

    def _load(self):
        if self.state_path is None:
            return
        game = self.session.game
        try:
            with open(self.state_path) as f:
                saved = json.load(f)
            game.board.set_fen(saved["fen"])
            if game.graveyard is not None:
                for f, r, symbol in saved["parked"]:
                    piece = chess.Piece.from_symbol(symbol)
                    game.graveyard.parked["white" if piece.color else "black"].append(((f, r), piece))
            self.session.rules = bool(saved["rules"])
        except OSError:
            return
        except (ValueError, KeyError, TypeError):
            game.reset()
            self.say("The saved grid could not be read, so the grid starts from the opening position.", error=True)
            return
        self.say("The grid is as it was left before the restart. If the pieces were moved since, fix it with put and remove.")

    def _describe(self, game, side):
        """The status line and the legal moves, by starting square, for a game's position."""
        board = game.board
        problems = game.problems()
        moves = {}
        if not problems:
            for move in board.legal_moves:
                targets = moves.setdefault(chess.square_name(move.from_square), [])
                target = chess.square_name(move.to_square)
                if target not in targets:
                    targets.append(target)
        if problems:
            status = "Not a playable position: " + "; ".join(problems)
        elif board.is_checkmate():
            status = "Checkmate: %s wins" % ("Black" if board.turn else "White")
        elif board.is_game_over():
            status = "Game over: a draw"
        else:
            status = "%s to move%s" % (side, ", and in check" if board.is_check() else "")
        return status, moves

    def _refresh(self):
        if not self.session.rules:
            self.status = "Rules are off: any piece can go anywhere"
            self.moves = {}
            return
        self.status, self.moves = self._describe(self.session.game, self.session.side())

    def _check_settings(self):
        settings = self.machine.settings()
        if settings.get("32") == "1" and self.ask(
            "Laser mode is on ($32=1): the engraver may switch the magnet off whenever "
            "the head stops. Turn laser mode off?", "Turn it off", "Leave it"
        ):
            self.machine.set_setting("32", "0")
        for key, axis in (("120", "X"), ("121", "Y")):
            try:
                value = float(settings.get(key, "0"))
            except ValueError:
                continue
            if value > HIGH_ACCELERATION and self.ask(
                "%s acceleration is %d mm/s2 ($%s): sharp starts and stops can make pieces slip. "
                "Lower it to %d mm/s2?" % (axis, int(value), key, SUGGESTED_ACCELERATION), "Lower it", "Leave it"
            ):
                self.machine.set_setting(key, SUGGESTED_ACCELERATION)

    def _start(self, after_dropout=False):
        """Connect to the engraver and have the players confirm where the head is.

        After a dropped connection the questions are skipped if the engraver
        still has the head where this program last sent it.
        """
        machine = self.machine
        trusted = machine.head if (after_dropout and self.ready) else None
        self.ready = False
        if isinstance(machine, FakeMachine):
            machine.head = machine.head or (0.0, 0.0)
            self.ready = True
            self.say("Practice mode: no engraver is connected, nothing really moves.")
            return
        if hasattr(machine, "connect"):
            machine.connect()
            if getattr(machine, "was_paused", False):
                self.say("The engraver had been left paused. The pause was ended and its unfinished moves dropped.")
        elif machine.out_of_step:
            raise MachineError("The connection to the engraver is out of step. Quit and start the program again.")
        else:
            machine.head = machine.position()
        if trusted and machine.head and all(abs(a - b) < 0.05 for a, b in zip(trusted, machine.head)):
            self.ready = True
            self.say("Reconnected to the engraver.")
            return
        self._check_settings()
        if self.cfg.get("homing_switches"):
            self.say("Homing...")
            machine.home()
        elif machine.head is None:
            raise MachineError("The engraver did not say where the head is. Press Reconnect to try again.")
        elif not self.ask(
            "The engraver counts the head as %.1f mm and %.1f mm away from its corner. It counts "
            "from where the head stood when the engraver was switched on, so this is only right if "
            "the head was in its corner then and nobody has pushed it by hand since. "
            "Is the head really there?" % machine.head, "Yes", "No"
        ):
            raise MachineError(
                "Push the head into its corner, switch the engraver off and on again, then press Reconnect."
            )
        self.ready = True
        self.say("Connected to the engraver. Ready to play.")
        self.sounds.play("start")

    def _outline(self):
        """Pull a piece round and round the corner squares, to check the board lines up.

        The players pause or end the run from the page; either takes effect
        at the next corner. The grid is left alone.
        """
        mover = self.session.game.mover
        machine = self.machine
        feed = self.cfg.get("outline_feed", 3000)
        mover.goto((0, 0))
        machine.wait_until_idle()
        if not self.ask("The magnet is under A1. Put a piece there to pull round the corners.", "Start", "Cancel"):
            return
        corner = "a1"
        machine.magnet(True)
        try:
            machine.dwell(mover.grab_seconds)
            i = 0
            while True:
                i += 1
                corner = OUTLINE_CORNERS[i % len(OUTLINE_CORNERS)]
                self.answer = None
                self.question = {
                    "text": "Pulling the piece round the corners. Next corner: %s." % corner.upper(),
                    "yes": "Pause there", "no": "End there",
                }
                x, y = mover.geometry.square_mm(corner)
                machine.move_to(x, y, feed)
                machine.wait_until_idle()
                if self.answer is False:
                    break
                if self.answer is True and not self.ask("Paused at %s." % corner.upper(), "Carry on", "End"):
                    break
        finally:
            self.question = None
            try:
                machine.magnet(False)
            except MachineError:
                pass
        machine.dwell(mover.grab_seconds)
        machine.wait_until_idle()
        self.say("The run round the corners ended at %s. The grid was not changed." % corner.upper())

    def _carry_out(self, command):
        kind = command[0]
        try:
            if kind == "reconnect":
                self._start()
                return
            if getattr(self.machine, "out_of_step", False):
                self._start(after_dropout=True)
            moves = kind in MOVING_COMMANDS or command == ("reset", "pieces")
            if moves and not self.ready:
                raise ValueError(
                    "The head's position hasn't been confirmed, so nothing can move. Press Reconnect."
                )
            if kind == "outline":
                self._outline()
                return
            for note in self.session.execute(command):
                self.say(note)
        except (ValueError, MachineError) as e:
            self.failed = True
            if not self.stopping:
                self.say(str(e), error=True)
                if kind == "move" and isinstance(e, ValueError):
                    self.sounds.play("invalid_move")
        except Exception as e:
            self.failed = True
            self.say("Something went wrong inside the program: %r" % e, error=True)
        finally:
            if self.stopping:
                self._stopped()
            self._refresh()
            self._save()

    def _stopped(self):
        try:
            self.machine.stop()
        except Exception:
            pass
        self.stopping = False
        if self.machine.head is None:
            self.ready = False
            self.say(
                "Stopped. The head's position is lost: push it into its corner, switch the "
                "engraver off and on again, then press Reconnect.", error=True
            )
        else:
            self.say(
                "Stopped. If a piece was on the move, put it back where the grid shows it "
                "(or use put and remove to match the real board).", error=True
            )

    def run(self):
        """Carry out queued commands forever."""
        self._carry_out(("reconnect",))
        while True:
            dropped = 0
            with self.lock:
                if self.failed:
                    # What was waiting counted on the command that went wrong.
                    dropped, self.queue = len(self.queue), []
                    self.failed = False
                command = self.queue.pop(0) if self.queue else None
                if command is None:
                    self.plan = self.planned = None
                    self.busy = False
            if self.stopping:
                # The stop came between two commands, with nothing running to catch it.
                self._stopped()
            if dropped:
                self.say("%d waiting move%s dropped." % (dropped, "" if dropped == 1 else "s"), error=True)
            if command is None:
                self.machine.idle()
                self.sounds.service()
                time.sleep(0.05)
            else:
                self._carry_out(command)


def _send_asset(conn, name):
    """One of the page's pictures. Only plain file names with a known ending are served."""
    kind = ASSET_TYPES.get(name.rsplit(".", 1)[-1])
    plain = all(ch.isalpha() or ch.isdigit() or ch in "-_." for ch in name) and ".." not in name
    try:
        if kind is None or not plain:
            raise OSError
        with open(ASSETS_PATH + name, "rb") as f:
            data = f.read()
    except OSError:
        respond(conn, b"Not found", "text/plain", "404 Not Found")
        return
    respond(conn, data, kind, cache=True)


def handle(conn, app):
    request = read_request(conn)
    if request is None:
        return
    method, path, body = request
    if method == "GET" and path == "/":
        with open(PAGE_PATH, "rb") as f:
            respond(conn, f.read(), "text/html; charset=utf-8")
    elif method == "GET" and path.startswith("/assets/"):
        _send_asset(conn, path[len("/assets/"):])
    elif method == "GET" and path == "/state":
        respond(conn, app.state())
    elif method == "POST" and path == "/command":
        accepted, message = app.submit(body)
        respond(conn, {"ok": accepted, "message": message})
    elif method == "POST" and path == "/answer":
        app.give_answer(body.strip() == "yes")
        respond(conn, {"ok": True, "message": ""})
    elif method == "POST" and path == "/voice" and app.voice is not None:
        app.voice.switch(body.strip() == "on")
        respond(conn, {"ok": True, "message": ""})
    elif method == "POST" and path == "/stop":
        accepted, message = app.stop()
        respond(conn, {"ok": accepted, "message": message})
    else:
        respond(conn, b"Not found", "text/plain", "404 Not Found")


def run(cfg, machine, port, host="0.0.0.0", state_path=None, sounds=None, magnet_sensor=None, make_voice=None):
    """Serve the page and play until the program is ended.

    make_voice(app), when given, returns the microphone listener that the
    page can switch on and off (see voice.Listener).
    """
    app = App(cfg, machine, state_path, sounds, magnet_sensor)
    if make_voice is not None:
        app.voice = make_voice(app)
    _thread.start_new_thread(serve, (app, port, host, handle))
    app.run()
