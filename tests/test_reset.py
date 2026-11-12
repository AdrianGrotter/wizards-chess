import chess
import pytest

from wizchess.game import Game, MoveInterrupted
from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine, MachineError
from wizchess.mover import Mover
from wizchess.reset import plan_reset


def board_after(*moves, fen=None):
    board = chess.Board(fen) if fen else chess.Board()
    for m in moves:
        board.push_san(m)
    return board


def replay(board, plan):
    """Apply a plan to a copy of the board, checking every drag lands on an empty square."""
    pieces = dict(board.piece_map())
    for sq in plan.extra:
        del pieces[sq]
    for s, t in plan.moves:
        assert t not in pieces, "drag onto occupied %s" % chess.square_name(t)
        pieces[t] = pieces.pop(s)
    for sq, p in plan.missing:
        assert sq not in pieces
        pieces[sq] = p
    return pieces


def test_starting_position_needs_nothing():
    plan = plan_reset(chess.Board())
    assert (plan.extra, plan.moves, plan.missing) == ([], [], [])


def test_simple_moves_are_undone():
    board = board_after("e4", "e5", "Nf3")
    plan = plan_reset(board)
    assert sorted(plan.moves) == sorted([(chess.E4, chess.E2), (chess.E5, chess.E7), (chess.F3, chess.G1)])
    assert replay(board, plan) == chess.Board().piece_map()


def test_captured_pieces_are_put_back_by_hand():
    board = board_after("e4", "d5", "exd5")
    plan = plan_reset(board)
    assert plan.missing == [(chess.D7, chess.Piece.from_symbol("p"))]
    assert replay(board, plan) == chess.Board().piece_map()


def test_swapped_pieces_step_aside_to_break_the_cycle():
    board = chess.Board()
    board.set_piece_at(chess.B1, chess.Piece.from_symbol("B"))
    board.set_piece_at(chess.C1, chess.Piece.from_symbol("N"))
    plan = plan_reset(board)
    assert len(plan.moves) == 3
    assert replay(board, plan) == chess.Board().piece_map()


def test_promoted_queen_is_lifted_off_and_the_pawn_put_back():
    board = chess.Board("4k3/8/8/8/8/8/8/Q2QK3 w - - 0 1")
    plan = plan_reset(board)
    assert len(plan.extra) == 1
    assert replay(board, plan) == chess.Board().piece_map()


@pytest.mark.parametrize("seed", range(20))
def test_any_scrambled_position_resets_cleanly(seed):
    import random

    rng = random.Random(seed)
    board = chess.Board()
    for _ in range(rng.randint(5, 60)):
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(rng.choice(moves))
    plan = plan_reset(board)
    assert replay(board, plan) == chess.Board().piece_map()


def make_game(machine, answers=None):
    answers = [] if answers is None else answers
    asked = []

    def ask_player(message):
        asked.append(message)
        return answers.pop(0) if answers else True

    game = Game(Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500), remove_by_hand=lambda sq: True)
    return game, asked, ask_player


def test_reset_drags_pieces_home_and_starts_a_new_game():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game, asked, ask_player = make_game(machine)
    for m in ["e4", "d5", "exd5", "Nf6"]:
        game.play(m)
    notes = game.reset_pieces(ask_player)
    assert asked == ["Put these pieces on the board: black pawn on D7."]
    assert game.board.fen() == chess.Board().fen()
    assert notes[-1] == "All pieces are on their starting squares. White to move."


def test_reset_can_be_called_off_before_lifting_pieces():
    machine = FakeMachine((300, 300), 1000, echo=False)
    game, asked, ask_player = make_game(machine, answers=[False])
    game.board.set_fen("4k3/8/8/8/8/8/8/Q2QK3 w - - 0 1")
    lines_before = len(machine.lines)
    with pytest.raises(ValueError, match="Reset called off"):
        game.reset_pieces(ask_player)
    assert len(machine.lines) == lines_before


class BreaksOnSecondDrag(FakeMachine):
    def magnet(self, on):
        if on and self.lines.count("M3 S1000") == 1:
            raise MachineError("No reply from the engraver")
        super().magnet(on)


def test_interrupted_reset_keeps_the_grid_accurate_so_far():
    machine = BreaksOnSecondDrag((300, 300), 1000, echo=False)
    game, _, ask_player = make_game(machine)
    game.board = board_after("e4", "e5")
    with pytest.raises(MoveInterrupted, match="run reset again"):
        game.reset_pieces(ask_player)
    pieces = game.board.piece_map()
    moved_home = (pieces.get(chess.E2) == chess.Piece.from_symbol("P")) + (pieces.get(chess.E7) == chess.Piece.from_symbol("p"))
    assert moved_home == 1
    assert len(pieces) == 32


def test_captured_pieces_are_parked_and_brought_back_by_the_magnet():
    from wizchess.game import Graveyard

    machine = FakeMachine((300, 320), 1000, echo=False)
    asked = []
    game = Game(
        Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500),
        Graveyard({"white": -1, "black": 8}),
    )
    for m in ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qxa2", "Rxa2"]:
        game.play(m)
    assert len(game.graveyard.parked["white"]) == 2
    assert len(game.graveyard.parked["black"]) == 2
    game.reset_pieces(lambda message: asked.append(message) or True)
    assert asked == []
    assert game.board.fen() == chess.Board().fen()
    assert game.graveyard.parked == {"white": [], "black": []}
