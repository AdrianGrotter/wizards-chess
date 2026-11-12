"""The game as a web page: a small HTTP server, and the loop that carries out what the page asks for.

Runs under both Python (on a laptop) and MicroPython (on the ESP32).
"""
import _thread
import json
import os
import socket
import time

import chess

from .game import Game, Graveyard
from .geometry import Geometry
from .grid import GRID_HELP, parse_command
from .machine import FakeMachine, MachineError
from .mover import Mover
from .session import GridSession

PAGE_PATH = __file__.rsplit("/", 1)[0] + "/page.html"
LOG_LENGTH = 40
SUGGESTED_ACCELERATION = 500
HIGH_ACCELERATION = 1000
MOVING_COMMANDS = ("move", "goto", "park")


class App:
    """One game, driven by commands that arrive from the web page.

    Commands run one at a time on the thread that calls run(); the web
    server's thread only hands them over, reads the state and asks for a stop.
    """

    def __init__(self, cfg, machine, state_path=None):
        """state_path names a file that keeps the grid across restarts of this program."""
        mover = Mover(machine, Geometry.from_config(cfg["board"]), cfg["travel_feed"], cfg["drag_feed"])
        graveyard = cfg.get("graveyard")
        game = Game(
            mover,
            Graveyard.from_config(graveyard) if graveyard else None,
            remove_by_hand=lambda name: self.ask("Take the captured piece off %s by hand." % name.upper()),
        )
        self.cfg = cfg
        self.machine = machine
        self.session = GridSession(game, cfg.get("slow_feed", 1500), self.ask)
        self.lock = _thread.allocate_lock()
        self.pending = None
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
            time.sleep(0.05)
        self.question = None
        return self.answer is True

    def give_answer(self, yes):
        if self.question is not None:
            self.answer = bool(yes)

    def submit(self, text):
        """Queue a typed command. Returns (accepted, message for the player)."""
        text = text.strip()
        if text.lower() == "reconnect":
            command = ("reconnect",)
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
        with self.lock:
            if self.busy or self.pending is not None:
                return False, "The board is still busy with the last command."
            self.pending = command
        return True, ""

    def stop(self):
        """Halt whatever the engraver is doing. Called from the web server's thread."""
        if not self.busy:
            return False, "Nothing is moving."
        self.stopping = True
        self.machine.interrupt()
        return True, ""

    def state(self):
        game = self.session.game
        head = self.machine.head
        parked = {"white": "", "black": ""}
        if game.graveyard is not None:
            for color in parked:
                parked[color] = "".join(piece.symbol() for _, piece in game.graveyard.parked[color])
        return {
            "pieces": {chess.square_name(sq): p.symbol() for sq, p in game.board.piece_map().items()},
            "parked": parked,
            "head": None if head is None else game.mover.geometry.square_at(head),
            "came_from": self.session.came_from,
            "rules": self.session.rules,
            "status": self.status,
            "moves": self.moves,
            "busy": self.busy,
            "ready": self.ready,
            "question": self.question,
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

    def _refresh(self):
        game = self.session.game
        board = game.board
        if not self.session.rules:
            self.status = "Rules are off: any piece can go anywhere"
            self.moves = {}
            return
        problems = game.problems()
        moves = {}
        if not problems:
            for move in board.legal_moves:
                targets = moves.setdefault(chess.square_name(move.from_square), [])
                target = chess.square_name(move.to_square)
                if target not in targets:
                    targets.append(target)
        self.moves = moves
        side = self.session.side()
        if problems:
            self.status = "Not a playable position: " + "; ".join(problems)
        elif board.is_checkmate():
            self.status = "Checkmate: %s wins" % ("Black" if board.turn else "White")
        elif board.is_game_over():
            self.status = "Game over: a draw"
        else:
            self.status = "%s to move%s" % (side, ", and in check" if board.is_check() else "")

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
            for note in self.session.execute(command):
                self.say(note)
        except (ValueError, MachineError) as e:
            if not self.stopping:
                self.say(str(e), error=True)
        except Exception as e:
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
            with self.lock:
                command = self.pending
                self.pending = None
                self.busy = command is not None
            if command is None:
                self.machine.idle()
                time.sleep(0.05)
            else:
                self._carry_out(command)


def _read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(512)
        if not chunk or len(data) > 8192:
            return None
        data += chunk
    split = data.index(b"\r\n\r\n")
    lines = data[:split].decode().split("\r\n")
    body = data[split + 4:]
    words = lines[0].split(" ")
    if len(words) < 2:
        return None
    length = 0
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    while len(body) < length:
        chunk = conn.recv(512)
        if not chunk:
            break
        body += chunk
    return words[0], words[1].split("?")[0], body.decode()


def _respond(conn, body, content_type="application/json", status="200 OK"):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    conn.sendall(
        ("HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
         "Cache-Control: no-store\r\nConnection: close\r\n\r\n" % (status, content_type, len(body))).encode()
    )
    conn.sendall(body)


def handle(conn, app):
    request = _read_request(conn)
    if request is None:
        return
    method, path, body = request
    if method == "GET" and path == "/":
        with open(PAGE_PATH, "rb") as f:
            _respond(conn, f.read(), "text/html; charset=utf-8")
    elif method == "GET" and path == "/state":
        _respond(conn, app.state())
    elif method == "POST" and path == "/command":
        accepted, message = app.submit(body)
        _respond(conn, {"ok": accepted, "message": message})
    elif method == "POST" and path == "/answer":
        app.give_answer(body.strip() == "yes")
        _respond(conn, {"ok": True, "message": ""})
    elif method == "POST" and path == "/stop":
        accepted, message = app.stop()
        _respond(conn, {"ok": accepted, "message": message})
    else:
        _respond(conn, b"Not found", "text/plain", "404 Not Found")


def serve(app, port, host="0.0.0.0"):
    """Answer the page's requests forever, one at a time."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(socket.getaddrinfo(host, port)[0][-1])
    server.listen(4)
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            continue
        try:
            conn.settimeout(2)
            handle(conn, app)
        except Exception:
            pass
        finally:
            conn.close()


def run(cfg, machine, port, host="0.0.0.0", state_path=None):
    """Serve the page and play until the program is ended."""
    app = App(cfg, machine, state_path)
    _thread.start_new_thread(serve, (app, port, host))
    app.run()
