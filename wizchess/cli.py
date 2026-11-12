import argparse

import chess

from . import config as config_file
from .game import Game, Graveyard
from .geometry import Geometry, parse_square
from .grid import GRID_HELP, parse_command, render
from .machine import FakeMachine, MachineError
from .mover import Mover, Step

JOG_HELP = """\
  x 10 / y -5   move the head 10 mm in x / -5 mm in y
  go 120 80     move the head to x=120, y=80 mm
  sq e4         move the head under e4, magnet off
  move e2 e4    drag a piece from e2 to e4 (add "edges" to go between squares)
  on / off      magnet on / off
  pos           show the head position
  save a1       store the current position as the centre of a1 (same for h8)
  quit          leave"""


def make_machine(cfg, fake):
    common = dict(
        travel_mm=cfg["travel_mm"],
        magnet_power=cfg["magnet_power"],
        homing_switches=cfg["homing_switches"],
    )
    if fake:
        return FakeMachine(**common)
    from .grbl import GrblMachine

    return GrblMachine(cfg["port"], cfg["baud"], **common)


def make_mover(cfg, machine):
    return Mover(machine, Geometry.from_config(cfg["board"]), cfg["travel_feed"], cfg["drag_feed"])


def cmd_info(cfg, machine, args):
    if isinstance(machine, FakeMachine):
        print("Fake machine: nothing to read.")
        return
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
        print("\nWarning: $32=1 switches the magnet off whenever the head stops. Send $32=0.")
    if (s.get("22") == "1") != bool(cfg["homing_switches"]):
        print("\nWarning: $22 and homing_switches in config.json disagree.")


def cmd_goto(cfg, machine, args):
    make_mover(cfg, machine).goto(parse_square(args.square))
    machine.wait_until_idle()


def cmd_move(cfg, machine, args):
    step = Step(parse_square(args.start), parse_square(args.end), via_edges=args.edges)
    make_mover(cfg, machine).run(step)


def cmd_home(cfg, machine, args):
    machine.home()


def make_game(cfg, machine):
    columns = cfg.get("graveyard_columns")

    def remove_by_hand(square):
        input("Take the captured piece off %s by hand, then press Enter." % square.upper())

    return Game(
        make_mover(cfg, machine),
        Graveyard(columns) if columns else None,
        remove_by_hand=remove_by_hand,
    )


def cmd_play(cfg, machine, args):
    game = make_game(cfg, machine)
    print("Type moves like e2e4 or Nf3. 'board' shows the board, 'quit' leaves.")
    while not game.board.is_game_over():
        side = "White" if game.board.turn else "Black"
        text = input("%s> " % side).strip()
        if text in ("quit", "exit"):
            return
        if text == "board":
            print(game.board)
            continue
        if not text:
            continue
        try:
            for note in game.play(text):
                print(note)
        except ValueError as e:
            print(e)


def grid_pieces(board):
    return {chess.square_name(sq): piece.symbol() for sq, piece in board.piece_map().items()}


def cmd_grid(cfg, machine, args):
    game = make_game(cfg, machine)
    head = came_from = None
    print(render(grid_pieces(game.board)))
    print(GRID_HELP)
    while True:
        side = "White" if game.board.turn == chess.WHITE else "Black"
        try:
            command = parse_command(input("%s> " % side))
        except ValueError as e:
            print(e)
            continue
        kind = command[0]
        try:
            if kind == "quit":
                return
            if kind == "help":
                print(GRID_HELP)
                continue
            if kind == "reset":
                game.board.reset()
                came_from = None
            elif kind == "clear":
                game.board.clear()
                came_from = None
            elif kind == "put":
                game.board.set_piece_at(chess.parse_square(command[1]), chess.Piece.from_symbol(command[2]))
            elif kind == "remove":
                game.board.remove_piece_at(chess.parse_square(command[1]))
            elif kind == "goto":
                game.mover.goto(parse_square(command[1]))
                machine.wait_until_idle()
                head = command[1]
            elif kind == "move":
                _, start, end, promotion = command
                notes = game.play_move(game.move_between(start, end, promotion))
                head, came_from = end, start
                print(render(grid_pieces(game.board), head, came_from))
                for note in notes:
                    print(note)
                continue
            print(render(grid_pieces(game.board), head, came_from))
        except (ValueError, MachineError) as e:
            print(e)


def cmd_jog(cfg, machine, args):
    mover = make_mover(cfg, machine)
    position = machine.position() or (0.0, 0.0)
    magnet_on = False
    print(JOG_HELP)
    while True:
        parts = input("jog (%.1f, %.1f)> " % position).split()
        if not parts:
            continue
        cmd = parts[0]
        try:
            if cmd == "quit":
                break
            elif cmd in ("x", "y"):
                delta = float(parts[1])
                target = (position[0] + delta, position[1]) if cmd == "x" else (position[0], position[1] + delta)
                machine.move_to(target[0], target[1], cfg["travel_feed"])
                position = target
            elif cmd == "go":
                target = (float(parts[1]), float(parts[2]))
                machine.move_to(target[0], target[1], cfg["travel_feed"])
                position = target
            elif cmd == "sq":
                mover.goto(parse_square(parts[1]))
                position = mover.geometry.square_mm(parts[1])
            elif cmd == "move":
                via_edges = len(parts) > 3 and parts[3] == "edges"
                mover.run(Step(parse_square(parts[1]), parse_square(parts[2]), via_edges))
                position = mover.geometry.square_mm(parts[2])
            elif cmd in ("on", "off"):
                magnet_on = cmd == "on"
                machine.magnet(magnet_on)
            elif cmd == "pos":
                print(machine.position() or position)
            elif cmd == "save" and parts[1] in ("a1", "h8"):
                cfg["board"][parts[1]] = [round(position[0], 2), round(position[1], 2)]
                config_file.save(cfg)
                print("Saved %s = %s to config.json" % (parts[1], cfg["board"][parts[1]]))
            else:
                print(JOG_HELP)
            machine.wait_until_idle()
        except (ValueError, IndexError) as e:
            print(e or JOG_HELP)
    if magnet_on:
        machine.magnet(False)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wizchess", description="Wizard chess on a GRBL engraver")
    parser.add_argument("--fake", action="store_true", help="print G-code instead of driving the engraver")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show engraver info and the settings that matter")
    p = sub.add_parser("goto", help="move the head under a square, magnet off")
    p.add_argument("square")
    p = sub.add_parser("move", help="drag a piece between two squares, no chess rules")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("--edges", action="store_true", help="travel along the lines between squares")
    sub.add_parser("home", help="run homing ($H), needs homing switches")
    sub.add_parser("play", help="play a game by typing moves")
    sub.add_parser("grid", help="interactive grid: type A4 C2 to move a piece, chess rules enforced")
    sub.add_parser("jog", help="interactive session: move the head, drag pieces, save calibration points")

    args = parser.parse_args(argv)
    cfg = config_file.load()
    machine = make_machine(cfg, args.fake)
    commands = {
        "info": cmd_info,
        "goto": cmd_goto,
        "move": cmd_move,
        "home": cmd_home,
        "play": cmd_play,
        "grid": cmd_grid,
        "jog": cmd_jog,
    }
    try:
        commands[args.command](cfg, machine, args)
    except KeyboardInterrupt:
        machine.magnet(False)
    finally:
        machine.close()
