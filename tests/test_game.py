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
    assert steps == [Step((3, 4), (8, 0), via_edges=True), Step((4, 3), (3, 4))]


def test_en_passant_removes_the_passed_pawn():
    steps = steps_after(["e2e4", "a7a6", "e4e5", "d7d5"], "e5d6")
    assert steps == [Step((3, 4), (8, 0), via_edges=True), Step((4, 4), (3, 5))]


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
