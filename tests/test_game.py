import chess
import pytest

from wizchess.game import Game, Graveyard, MoveInterrupted, physical_steps
from wizchess.machine import MachineError
from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine
from wizchess.mover import Mover, Step

ROWS = {"white": -1, "black": 8}


def steps_after(moves, last):
    board = chess.Board()
    for m in moves:
        board.push_uci(m)
    return physical_steps(board, chess.Move.from_uci(last), Graveyard(ROWS))


def test_pawn_moves_straight():
    assert steps_after([], "e2e4") == [Step((4, 1), (4, 3), via_edges=None)]


def test_knight_goes_around():
    assert steps_after([], "g1f3") == [Step((6, 0), (5, 2), via_edges=None)]


def test_capture_clears_the_square_first():
    steps = steps_after(["e2e4", "d7d5"], "e4d5")
    assert steps == [Step((3, 4), (3.5, 8), leaves_board=True), Step((4, 3), (3, 4), via_edges=None)]


def test_en_passant_removes_the_passed_pawn():
    steps = steps_after(["e2e4", "a7a6", "e4e5", "d7d5"], "e5d6")
    assert steps == [Step((3, 4), (3.5, 8), leaves_board=True), Step((4, 4), (3, 5), via_edges=None)]


def test_kingside_castling_moves_king_then_rook():
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"]
    assert steps_after(moves, "e1g1") == [
        Step((4, 0), (6, 0)),
        Step((7, 0), (5, 0), via_edges=None),
    ]


def test_graveyard_rows_fill_from_the_middle_outwards():
    g = Graveyard(ROWS)
    pawn = chess.Piece.from_symbol("p")
    slots = [g.park(pawn) for _ in range(5)]
    assert slots == [(3.5, 8), (3.0, 8), (4.0, 8), (2.5, 8), (4.5, 8)]
    assert g.park(chess.Piece.from_symbol("N")) == (3.5, -1)


def test_graveyard_row_holds_every_piece_a_side_can_lose():
    g = Graveyard(ROWS)
    for _ in range(15):
        g.park(chess.Piece.from_symbol("p"))
    assert all(-0.5 <= f <= 7.5 for f, _ in g.slots["black"])
    assert len(g.slots["black"]) == 17


def test_graveyard_full():
    g = Graveyard(ROWS, spacing=1)
    for _ in range(9):
        g.park(chess.Piece.from_symbol("p"))
    with pytest.raises(ValueError, match="No room left"):
        g.park(chess.Piece.from_symbol("p"))


def test_graveyard_gives_back_the_right_piece():
    g = Graveyard(ROWS)
    g.park(chess.Piece.from_symbol("p"))
    knight_slot = g.park(chess.Piece.from_symbol("n"))
    assert g.take_back(chess.Piece.from_symbol("n")) == knight_slot
    assert g.take_back(chess.Piece.from_symbol("n")) is None
    assert g.peek_slot("black") == knight_slot


def test_game_accepts_uci_and_san_and_rejects_illegal():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game = Game(Mover(machine, Geometry((60, 60), (235, 60), (60, 235)), 3000, 1500), Graveyard(ROWS))
    game.play("e2e4")
    game.play("e5")
    with pytest.raises(ValueError):
        game.play("e4e5")
    assert game.board.fullmove_number == 2


def test_scholars_mate_reports_checkmate():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game = Game(Mover(machine, Geometry((60, 60), (235, 60), (60, 235)), 3000, 1500), Graveyard(ROWS))
    notes = []
    for m in ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7"]:
        notes = game.play(m)
    assert notes == ["Checkmate."]


def test_without_graveyard_the_captured_piece_is_left_to_the_players():
    assert steps_after_no_graveyard(["e2e4", "d7d5"], "e4d5") == [Step((4, 3), (3, 4), via_edges=None)]


def steps_after_no_graveyard(moves, last):
    board = chess.Board()
    for m in moves:
        board.push_uci(m)
    return physical_steps(board, chess.Move.from_uci(last), None)


def test_game_asks_for_the_captured_piece_before_moving():
    machine = FakeMachine((300, 300), 1000, echo=False)
    removed = []

    def remove_by_hand(square):
        removed.append((square, len(machine.lines)))

    game = Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500), remove_by_hand=remove_by_hand)
    game.play("e4")
    game.play("d5")
    lines_before_capture = len(machine.lines)
    game.play("exd5")
    assert removed == [("d5", lines_before_capture)]


def new_game():
    machine = FakeMachine((300, 300), 1000, echo=False)
    return Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500), remove_by_hand=lambda sq: None)


@pytest.mark.parametrize(
    "start, end, reason",
    [
        ("e4", "e5", "no piece on E4"),
        ("e7", "e5", "White's turn"),
        ("g1", "g3", "knight can't move"),
        ("e2", "e5", "pawn can't move"),
        ("a1", "a3", "The rook on A1 is blocked by your pawn on A2."),
        ("c1", "e3", "The bishop on C1 is blocked by your pawn on D2."),
        ("d1", "d5", "The queen on D1 is blocked by your pawn on D2."),
        ("e1", "g1", "occupied by your own knight"),
        ("a1", "a2", "occupied by your own pawn"),
    ],
)
def test_illegal_moves_say_why(start, end, reason):
    with pytest.raises(ValueError, match="(?i)" + reason):
        new_game().move_between(start, end)


def test_pinned_piece_cannot_expose_the_king():
    game = new_game()
    for m in ["e4", "e5", "d3", "Bb4"]:
        game.play(m)
    with pytest.raises(ValueError, match="check"):
        game.move_between("a2", "a3")


def test_pawn_promotes_to_queen_unless_told_otherwise():
    game = new_game()
    game.board.set_fen("8/4P3/8/8/8/8/k7/4K3 w - - 0 1")
    assert game.move_between("e7", "e8").promotion == chess.QUEEN
    assert game.move_between("e7", "e8", "n").promotion == chess.KNIGHT


def test_only_promoting_pawns_take_a_promotion_piece():
    with pytest.raises(ValueError, match="promoted"):
        new_game().move_between("e2", "e4", "q")


def test_castling_by_moving_the_king_two_squares():
    game = new_game()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"]:
        game.play(m)
    game.play_move(game.move_between("e1", "g1"))
    assert game.board.piece_at(chess.F1).symbol() == "R"


def test_blocked_by_the_other_side():
    game = new_game()
    for m in ["e4", "e5"]:
        game.play(m)
    with pytest.raises(ValueError, match="A pawn can't capture straight ahead: E5 is held by Black's pawn."):
        game.move_between("e4", "e5")


def test_pawn_double_step_blocked():
    game = new_game()
    for m in ["Nf3", "e6", "Ne5", "a6", "Ng4", "Bc5", "Ne3", "a5"]:
        game.play(m)
    with pytest.raises(ValueError, match="The pawn on E2 is blocked by your knight on E3."):
        game.move_between("e2", "e4")


def test_castling_blocked_by_a_piece_in_between():
    game = new_game()
    for m in ["e4", "e5", "Nf3", "Nc6"]:
        game.play(m)
    with pytest.raises(ValueError, match="The king on E1 is blocked by your bishop on F1."):
        game.move_between("e1", "g1")


def test_rook_blocked_further_along():
    game = new_game()
    game.board.set_fen("4k3/8/8/p7/8/8/8/R3K3 w - - 0 1")
    with pytest.raises(ValueError, match="The rook on A1 is blocked by Black's pawn on A5."):
        game.move_between("a1", "a8")


def test_grid_move_captures_an_opponents_piece():
    game = new_game()
    for m in ["e4", "d5"]:
        game.play(m)
    removed = []
    game.remove_by_hand = removed.append
    game.play_move(game.move_between("e4", "d5"))
    assert removed == ["d5"]
    assert game.board.piece_at(chess.D5).symbol() == "P"
    assert len(game.board.piece_map()) == 31


@pytest.mark.parametrize(
    "setup, start, end, message",
    [
        (["e4", "e5"], "d1", "d2", "D2 is occupied by your own pawn."),
        (["e4", "e5"], "f1", "g2", "G2 is occupied by your own pawn."),
        (["e4", "e5"], "e8", "e7", "It's White's turn."),
        (["e4", "e5", "Nf3"], "d8", "d7", "D7 is occupied by your own pawn."),
    ],
)
def test_friendly_pieces_cannot_be_taken(setup, start, end, message):
    game = new_game()
    for m in setup:
        game.play(m)
    with pytest.raises(ValueError, match=message):
        game.move_between(start, end)


class BreaksOnDrag(FakeMachine):
    """Fails on the nth magnet-on, to simulate the engraver failing mid-move."""

    def __init__(self, fail_on_grab):
        super().__init__((300, 300), 1000, echo=False)
        self.fail_on_grab = fail_on_grab

    def magnet(self, on):
        if on and self.lines.count("M3 S1000") + 1 == self.fail_on_grab:
            raise MachineError("No reply from the engraver")
        super().magnet(on)


def castling_ready_game(machine):
    game = Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500))
    for m in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"]:
        game.play(m)
    return game


def test_interrupted_move_says_what_happened_and_keeps_the_old_position():
    machine = BreaksOnDrag(fail_on_grab=99)
    game = castling_ready_game(machine)
    machine.fail_on_grab = machine.lines.count("M3 S1000") + 2
    fen_before = game.board.fen()
    with pytest.raises(MoveInterrupted) as error:
        game.play_move(game.move_between("e1", "g1"))
    message = str(error.value)
    assert "E1 to G1: done" in message
    assert "H1 to F1: may have stopped partway" in message
    assert "still shows the position before the move" in message
    assert game.board.fen() == fen_before


def test_interrupted_capture_reminds_about_the_removed_piece():
    machine = BreaksOnDrag(fail_on_grab=99)
    game = Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500), remove_by_hand=lambda sq: True)
    game.play("e4")
    game.play("d5")
    machine.fail_on_grab = machine.lines.count("M3 S1000") + 1
    with pytest.raises(MoveInterrupted, match="You took the piece off D5"):
        game.play_move(game.move_between("e4", "d5"))


def test_capture_can_be_called_off_before_anything_moves():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game = Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500), remove_by_hand=lambda sq: False)
    game.play("e4")
    game.play("d5")
    lines_before = len(machine.lines)
    with pytest.raises(ValueError, match="called off"):
        game.play_move(game.move_between("e4", "d5"))
    assert len(machine.lines) == lines_before
    assert game.board.piece_at(chess.D5).symbol() == "p"


def test_bad_route_is_refused_before_asking_for_the_captured_piece():
    machine = FakeMachine((100, 100), 1000, echo=False)
    asked = []
    game = Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500), remove_by_hand=asked.append)
    game.board.set_fen("4k3/7p/8/8/8/8/8/4K2R w - - 0 1")
    with pytest.raises(ValueError, match="outside the machine"):
        game.play_move(game.move_between("h1", "h7"))
    assert asked == []


def test_graveyard_slot_is_only_used_when_the_move_happens():
    machine = BreaksOnDrag(fail_on_grab=1)
    graveyard = Graveyard(ROWS)
    game = Game(Mover(machine, Geometry((31, 31), (234, 31), (31, 234)), 3000, 1500), graveyard)
    game.board.set_fen("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    with pytest.raises(MoveInterrupted):
        game.play_move(game.move_between("e4", "d5"))
    assert graveyard.parked == {"white": [], "black": []}


def test_castling_after_the_king_has_moved_says_so():
    game = new_game()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "Ke2", "Be7", "Ke1", "Bb4"]:
        game.play(m)
    with pytest.raises(ValueError, match="White can no longer castle on that side"):
        game.move_between("e1", "g1")


@pytest.mark.parametrize(
    "edit, problem",
    [
        (lambda g: g.remove("e1"), "White has no king"),
        (lambda g: g.put("d4", "K"), "more than one king"),
        (lambda g: g.put("d8", "P"), "pawn stands on the first or last row"),
        (lambda g: g.clear(), "the grid is empty"),
    ],
)
def test_impossible_positions_block_moves_with_a_reason(edit, problem):
    game = new_game()
    edit(game)
    assert any(problem in p for p in game.problems())
    with pytest.raises(ValueError, match="can't be checked until the grid is a real chess position"):
        game.move_between("a2", "a3")


def test_hand_edits_drop_castling_that_is_no_longer_possible():
    game = new_game()
    game.remove("h1")
    game.put("h3", "R")
    assert game.problems() == []
    with pytest.raises(ValueError):
        game.move_between("e1", "g1")


def test_turn_can_be_set_after_editing():
    game = new_game()
    game.set_turn("black")
    assert game.move_between("e7", "e5") == chess.Move.from_uci("e7e5")


def test_free_move_goes_anywhere_between_the_other_pieces():
    machine = FakeMachine((300, 320), 1000, echo=False)
    game = Game(Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500))
    game.free_move("a1", "a5")
    assert game.board.piece_at(chess.A5).symbol() == "R"
    assert game.board.piece_at(chess.A1) is None
    assert game.board.turn == chess.WHITE
    drag = machine.lines[machine.lines.index("M3 S1000") + 2:machine.lines.index("M5")]
    assert drag == [
        "G53 G1 X48.00 Y58.00 F1500",
        "G53 G1 X48.00 Y160.00 F1500",
        "G53 G1 X31.00 Y177.00 F1500",
    ]


def test_free_move_onto_a_piece_parks_it_first():
    machine = FakeMachine((300, 320), 1000, echo=False)
    graveyard = Graveyard(ROWS)
    game = Game(Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500), graveyard)
    game.free_move("a1", "a8")
    assert game.board.piece_at(chess.A8).symbol() == "R"
    assert graveyard.parked["black"] == [((3.5, 8.0), chess.Piece.from_symbol("r"))]


def test_free_move_from_an_empty_square_is_refused():
    with pytest.raises(ValueError, match="There is no piece on E4"):
        new_game().free_move("e4", "e5")


def drag_lines(machine):
    start = machine.lines.index("M3 S1000")
    return [l for l in machine.lines[start:machine.lines.index("M5", start)] if l.startswith("G53")]


def test_pawn_and_queen_moves_go_straight():
    machine = FakeMachine((300, 320), 1000, echo=False)
    game = Game(Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500))
    game.play("e4")
    assert drag_lines(machine) == ["G53 G1 X167.00 Y143.00 F1500"]
    game.play("e5")
    machine.lines.clear()
    game.play("Qh5")
    assert drag_lines(machine) == ["G53 G1 X269.00 Y177.00 F1500"]


def test_knight_takes_the_gutters_only_when_hemmed_in():
    machine = FakeMachine((300, 320), 1000, echo=False)
    game = Game(Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500))
    game.play("Nf3")
    assert len(drag_lines(machine)) == 3
    game.board.set_fen("4k3/8/8/8/8/8/8/4K1N1 w - - 0 1")
    machine.lines.clear()
    game.play("Nf3")
    assert drag_lines(machine) == ["G53 G1 X201.00 Y109.00 F1500"]


def test_free_move_along_an_empty_file_goes_straight():
    machine = FakeMachine((300, 320), 1000, echo=False)
    game = Game(Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500))
    game.board.set_fen("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    game.free_move("a1", "a7")
    assert drag_lines(machine) == ["G53 G1 X31.00 Y245.00 F1500"]
