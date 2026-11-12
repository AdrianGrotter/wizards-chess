import chess
import pytest

from wizchess.game import Game, Graveyard, physical_steps
from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine
from wizchess.mover import Mover, Step

COLUMNS = {"white": [-1, -2], "black": [8, 9]}


def steps_after(moves, last):
    board = chess.Board()
    for m in moves:
        board.push_uci(m)
    return physical_steps(board, chess.Move.from_uci(last), Graveyard(COLUMNS))


def test_pawn_moves_straight():
    assert steps_after([], "e2e4") == [Step((4, 1), (4, 3))]


def test_knight_goes_around():
    assert steps_after([], "g1f3") == [Step((6, 0), (5, 2), via_edges=True)]


def test_capture_clears_the_square_first():
    steps = steps_after(["e2e4", "d7d5"], "e4d5")
    assert steps == [Step((3, 4), (8, 0), via_edges=True, leaves_board=True), Step((4, 3), (3, 4))]


def test_en_passant_removes_the_passed_pawn():
    steps = steps_after(["e2e4", "a7a6", "e4e5", "d7d5"], "e5d6")
    assert steps == [Step((3, 4), (8, 0), via_edges=True, leaves_board=True), Step((4, 4), (3, 5))]


def test_kingside_castling_moves_king_then_rook():
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"]
    assert steps_after(moves, "e1g1") == [
        Step((4, 0), (6, 0)),
        Step((7, 0), (5, 0), via_edges=True),
    ]


def test_graveyard_fills_columns_in_order():
    g = Graveyard({"white": [-1, -2], "black": [8]})
    slots = [g.next_slot("white") for _ in range(9)]
    assert slots[0] == (-1, 0) and slots[7] == (-1, 7) and slots[8] == (-2, 0)


def test_graveyard_full():
    g = Graveyard({"white": [-1], "black": [8]})
    for _ in range(8):
        g.next_slot("black")
    with pytest.raises(RuntimeError):
        g.next_slot("black")


def test_game_accepts_uci_and_san_and_rejects_illegal():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game = Game(Mover(machine, Geometry((60, 60), (235, 235)), 3000, 1500), Graveyard(COLUMNS))
    game.play("e2e4")
    game.play("e5")
    with pytest.raises(ValueError):
        game.play("e4e5")
    assert game.board.fullmove_number == 2


def test_scholars_mate_reports_checkmate():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game = Game(Mover(machine, Geometry((60, 60), (235, 235)), 3000, 1500), Graveyard(COLUMNS))
    notes = []
    for m in ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7"]:
        notes = game.play(m)
    assert notes == ["Checkmate."]


def test_without_graveyard_the_captured_piece_is_left_to_the_players():
    assert steps_after_no_graveyard(["e2e4", "d7d5"], "e4d5") == [Step((4, 3), (3, 4))]


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

    game = Game(Mover(machine, Geometry((31, 31), (269, 269)), 3000, 1500), remove_by_hand=remove_by_hand)
    game.play("e4")
    game.play("d5")
    lines_before_capture = len(machine.lines)
    game.play("exd5")
    assert removed == [("d5", lines_before_capture)]


def new_game():
    machine = FakeMachine((300, 300), 1000, echo=False)
    return Game(Mover(machine, Geometry((31, 31), (269, 269)), 3000, 1500), remove_by_hand=lambda sq: None)


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
