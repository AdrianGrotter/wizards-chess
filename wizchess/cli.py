import argparse
import sys

import chess

from . import config as config_file
from .game import Game, Graveyard
from .geometry import Geometry, parse_square
from .grid import GRID_HELP, parse_command, render, square
from .machine import FakeMachine, MachineError
from .mover import Mover, Step

JOG_HELP = """\
  x 10 / y -5   move the head 10 mm in x / -5 mm in y
  go 120 80     move the head to x=120, y=80 mm
  sq e4         move the head under e4, magnet off
  move e2 e4    drag a piece from e2 to e4 (add "edges" to go between squares)
  on / off      magnet on / off
  pos           show the head position
  save a1       store the head position as the centre of a1 (also h1 and a8)
  unlock        clear an engraver alarm
  quit          send the head back to its corner and leave"""

CALIBRATION_SQUARES = ("a1", "h1", "a8")
SUGGESTED_ACCELERATION = 500
HIGH_ACCELERATION = 1000


def ask(prompt):
    """input() that turns Ctrl-D and Ctrl-C at a prompt into 'quit'."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return "quit"


def confirm(question):
    return ask(question + " [y/N] ").strip().lower() in ("y", "yes")


def make_machine(cfg, fake):
    common = dict(
        travel_mm=cfg["travel_mm"],
        magnet_power=cfg["magnet_power"],
        homing_switches=cfg["homing_switches"],
    )
    if fake:
        return FakeMachine(**common)
    from .grbl import GrblMachine

    return GrblMachine(cfg.get("port", "auto"), cfg["baud"], **common)


def make_mover(cfg, machine):
    return Mover(machine, Geometry.from_config(cfg["board"]), cfg["travel_feed"], cfg["drag_feed"])


def prepare(cfg, machine):
    """Check the engraver's settings and the head's zero before anything moves.

    Returns False when the head isn't in its corner and the session must not start.
    """
    if isinstance(machine, FakeMachine):
        return True
    settings = machine.settings()
    if settings.get("32") == "1":
        print("Laser mode is on ($32=1): the engraver may switch the magnet off whenever the head stops.")
        if confirm("Turn laser mode off ($32=0)?"):
            machine.set_setting("32", "0")
    for key, axis in (("120", "X"), ("121", "Y")):
        try:
            value = float(settings.get(key, "0"))
        except ValueError:
            continue
        if value > HIGH_ACCELERATION:
            print(
                "%s acceleration is %g mm/s2 ($%s): sharp starts and stops can make pieces slip."
                % (axis, value, key)
            )
            if confirm("Lower it to %d mm/s2?" % SUGGESTED_ACCELERATION):
                machine.set_setting(key, SUGGESTED_ACCELERATION)
    if (settings.get("22") == "1") != bool(cfg["homing_switches"]):
        print("Warning: homing on the engraver ($22) and homing_switches in config.json disagree.")
    if cfg["homing_switches"]:
        print("Homing...")
        machine.home()
        return True
    print("The engraver counts every position from where the head is right now.")
    if confirm("Is the head pushed all the way into its corner?"):
        return True
    print("Push the head into its corner by hand, then start again.")
    return False


def finish(mover):
    """Park the head so the next session starts counting from the corner."""
    if mover.machine.head is None:
        print("The head's position is unknown: push it back into its corner before the next run.")
        return
    mover.park()
    print("Head parked in its corner.")


def head_square(mover):
    head = mover.machine.head
    return None if head is None else mover.geometry.square_at(head)


def cmd_info(cfg, machine, args):
    if isinstance(machine, FakeMachine):
        print("Fake machine: nothing to read.")
        return
    print("Port          %s" % machine.serial.port)
    for line in machine.info():
        print(line)
    s = machine.settings()
    print()
    print("Work area     $130 x $131 = %s x %s mm" % (s.get("130"), s.get("131")))
    print("Max speed     $110 / $111 = %s / %s mm/min" % (s.get("110"), s.get("111")))
    print("Acceleration  $120 / $121 = %s / %s mm/s2" % (s.get("120"), s.get("121")))
    print("Magnet max    $30 = %s" % s.get("30"))
    print("Laser mode    $32 = %s" % s.get("32"))
    print("Homing        $22 = %s" % s.get("22"))
    print("Head now at   %s" % (machine.position(),))
    if s.get("32") == "1":
        print("\nWarning: $32=1 may switch the magnet off whenever the head stops.")
    if (s.get("22") == "1") != bool(cfg["homing_switches"]):
        print("\nWarning: $22 and homing_switches in config.json disagree.")


def cmd_goto(cfg, machine, args):
    mover = make_mover(cfg, machine)
    mover.goto(parse_square(square(args.square)))
    machine.wait_until_idle()
    ask("The head is under %s. Press Enter to send it back to its corner. " % args.square.upper())
    finish(mover)


def cmd_move(cfg, machine, args):
    mover = make_mover(cfg, machine)
    mover.run(Step(parse_square(square(args.start)), parse_square(square(args.end)), via_edges=args.edges))
    finish(mover)


def cmd_home(cfg, machine, args):
    machine.home()


def tell_player(message):
    answer = ask(message + "\nPress Enter when done (or type 'cancel'). ")
    return answer.strip().lower() not in ("cancel", "c", "quit")


def make_game(cfg, machine):
    graveyard = cfg.get("graveyard")

    def remove_by_hand(name):
        answer = ask(
            "Take the captured piece off %s by hand, then press Enter (or type 'cancel'). " % name.upper()
        )
        return answer.strip().lower() not in ("cancel", "c", "quit")

    return Game(
        make_mover(cfg, machine),
        Graveyard.from_config(graveyard) if graveyard else None,
        remove_by_hand=remove_by_hand,
    )


def cmd_play(cfg, machine, args):
    game = make_game(cfg, machine)
    print("Type moves like e2e4 or Nf3. 'board' shows the board, 'quit' leaves.")
    while not game.board.is_game_over():
        side = "White" if game.board.turn else "Black"
        text = ask("%s> " % side).strip()
        if text in ("quit", "exit"):
            break
        if text == "board":
            print(game.board)
            continue
        if not text:
            continue
        try:
            for note in game.play(text):
                print(note)
        except (ValueError, MachineError) as e:
            print(e)
    finish(game.mover)


def grid_pieces(board):
    return {chess.square_name(sq): piece.symbol() for sq, piece in board.piece_map().items()}


def cmd_grid(cfg, machine, args):
    game = make_game(cfg, machine)
    came_from = None
    rules = True
    print(render(grid_pieces(game.board), head_square(game.mover)))
    print(GRID_HELP)
    while True:
        side = "White" if game.board.turn == chess.WHITE else "Black"
        try:
            command = parse_command(ask("%s> " % (side if rules else "Free")))
        except ValueError as e:
            print(e)
            continue
        kind = command[0]
        notes = []
        try:
            if kind == "quit":
                break
            if kind == "help":
                print(GRID_HELP)
                continue
            if kind == "reset" and command[1] == "grid":
                game.reset()
                came_from = None
            elif kind == "reset":
                came_from = None
                notes = game.reset_pieces(tell_player)
                game.mover.park()
            elif kind == "park":
                game.mover.park()
            elif kind == "unlock":
                machine.unlock()
                notes.append("Alarm cleared.")
            elif kind == "clear":
                game.clear()
                came_from = None
            elif kind == "put":
                game.put(command[1], command[2])
            elif kind == "remove":
                game.remove(command[1])
            elif kind == "turn":
                game.set_turn(command[1])
            elif kind == "rules":
                rules = command[1] == "on"
                notes.append(
                    "Moves follow the chess rules again." if rules
                    else "Rules are off: any piece can go to any square. Type 'rules on' to go back."
                )
                if rules:
                    notes.extend("Note: %s." % p for p in game.problems())
            elif kind == "goto":
                game.mover.goto(parse_square(command[1]))
                machine.wait_until_idle()
            elif kind == "move":
                _, start, end, promotion = command
                if rules:
                    notes = game.play_move(game.move_between(start, end, promotion))
                else:
                    notes = game.free_move(start, end)
                came_from = start
            if kind in ("clear", "put", "remove", "turn"):
                notes.extend("Note: %s." % p for p in game.problems())
        except (ValueError, MachineError) as e:
            notes.append(str(e))
        print(render(grid_pieces(game.board), head_square(game.mover), came_from))
        for note in notes:
            print(note)
    finish(game.mover)


OUTLINE_CORNERS = ("a1", "a8", "h8", "h1")


def cmd_outline(cfg, machine, args):
    """Visit the corner squares in a circle, one per Enter, to check the board lines up."""
    mover = make_mover(cfg, machine)
    print("The head visits A1, A8, H8 and H1 in turn. Press Enter for the next corner, type 'quit' to stop.")
    i = 0
    while True:
        name = OUTLINE_CORNERS[i % len(OUTLINE_CORNERS)]
        x, y = mover.geometry.square_mm(name)
        machine.move_to(x, y, cfg["travel_feed"])
        machine.wait_until_idle()
        following = OUTLINE_CORNERS[(i + 1) % len(OUTLINE_CORNERS)]
        answer = ask("At %s (%.1f, %.1f mm). Enter for %s, or 'quit': " % (name.upper(), x, y, following.upper()))
        if answer.strip().lower() in ("quit", "q", "exit"):
            break
        i += 1
    finish(mover)


def _numbers(values, count, usage):
    if len(values) != count:
        raise ValueError(usage)
    try:
        return [float(v) for v in values]
    except ValueError:
        raise ValueError(usage)


def cmd_jog(cfg, machine, args):
    mover = make_mover(cfg, machine)
    magnet_on = False
    print(JOG_HELP)
    while True:
        head = machine.head
        prompt = "jog (%.1f, %.1f)> " % head if head else "jog (position unknown)> "
        parts = ask(prompt).split()
        if not parts:
            continue
        cmd, rest = parts[0].lower(), parts[1:]
        try:
            if cmd == "quit":
                break
            elif cmd in ("x", "y"):
                (delta,) = _numbers(rest, 1, "Use %s with a distance in mm, like: %s 10" % (cmd, cmd))
                if head is None:
                    raise ValueError("The head's position is unknown, so it can't move relative to it.")
                x, y = head
                machine.move_to(x + delta if cmd == "x" else x, y + delta if cmd == "y" else y, cfg["travel_feed"])
            elif cmd == "go":
                x, y = _numbers(rest, 2, "Use go with x and y in mm, like: go 120 80")
                machine.move_to(x, y, cfg["travel_feed"])
            elif cmd == "sq":
                if len(rest) != 1:
                    raise ValueError("Use sq with one square, like: sq e4")
                mover.goto(parse_square(square(rest[0])))
            elif cmd == "move":
                if len(rest) not in (2, 3) or (len(rest) == 3 and rest[2].lower() != "edges"):
                    raise ValueError('Use move with two squares, like: move e2 e4 (add "edges" to go between squares)')
                start, end = parse_square(square(rest[0])), parse_square(square(rest[1]))
                mover.run(Step(start, end, via_edges=len(rest) == 3))
            elif cmd in ("on", "off"):
                magnet_on = cmd == "on"
                machine.magnet(magnet_on)
            elif cmd == "pos":
                print(machine.position() or head)
            elif cmd == "save":
                if len(rest) != 1 or rest[0].lower() not in CALIBRATION_SQUARES:
                    raise ValueError("Use save with a1, h1 or a8, like: save a1")
                if head is None:
                    raise ValueError("The head's position is unknown, so there is nothing to save.")
                name = rest[0].lower()
                cfg["board"][name] = [round(head[0], 2), round(head[1], 2)]
                mover.geometry = Geometry.from_config(cfg["board"])
                config_file.save(cfg)
                print("Saved %s = %s to config.json" % (name, cfg["board"][name]))
            elif cmd == "unlock":
                machine.unlock()
                print("Alarm cleared.")
            else:
                print("Unknown command '%s'.\n%s" % (cmd, JOG_HELP))
                continue
            machine.wait_until_idle()
        except (ValueError, MachineError) as e:
            print(e)
    if magnet_on:
        machine.magnet(False)
    finish(mover)


COMMANDS = {
    "info": cmd_info,
    "goto": cmd_goto,
    "move": cmd_move,
    "home": cmd_home,
    "play": cmd_play,
    "grid": cmd_grid,
    "jog": cmd_jog,
    "outline": cmd_outline,
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wizchess", description="Wizard chess on a GRBL engraver")
    parser.add_argument("--fake", action="store_true", help="print G-code instead of driving the engraver")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show engraver info and the settings that matter")
    p = sub.add_parser("goto", help="move the head under a square, then back to its corner")
    p.add_argument("square")
    p = sub.add_parser("move", help="drag a piece between two squares, no chess rules")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("--edges", action="store_true", help="travel along the lines between squares")
    sub.add_parser("home", help="run homing ($H), needs homing switches")
    sub.add_parser("play", help="play a game by typing moves")
    sub.add_parser("grid", help="interactive grid: type A4 C2 to move a piece, chess rules enforced")
    sub.add_parser("jog", help="interactive session: move the head, drag pieces, save calibration points")
    sub.add_parser("outline", help="visit the corner squares A1, A8, H8, H1 in a circle, one per Enter")

    args = parser.parse_args(argv)
    cfg = config_file.load()
    try:
        machine = make_machine(cfg, args.fake)
    except MachineError as e:
        print(e)
        return 1
    try:
        if args.command != "info" and not prepare(cfg, machine):
            return 1
        COMMANDS[args.command](cfg, machine, args)
    except KeyboardInterrupt:
        machine.stop()
        print(
            "\nStopped. If the head was moving, its position is lost: "
            "push it back into its corner before the next run."
        )
        return 1
    except (ValueError, MachineError) as e:
        print(e)
        return 1
    finally:
        machine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
