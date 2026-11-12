"""The MicroPython chess rules (esp32/chess.py) must agree with python-chess."""
import importlib.util
import random
from pathlib import Path

import chess
import pytest

_spec = importlib.util.spec_from_file_location("minichess", Path(__file__).parent.parent / "esp32" / "chess.py")
mini = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mini)


def ucis(moves):
    return sorted(m.uci() for m in moves)


def flags(module, status):
    return {name for name in dir(mini) if name.startswith("STATUS_") and status & getattr(module, name)}


def assert_same(real, small):
    assert small.fen() == real.fen()
    assert ucis(small.legal_moves) == ucis(real.legal_moves)
    assert small.is_check() == real.is_check()
    assert small.is_checkmate() == real.is_checkmate()
    assert small.is_game_over() == real.is_game_over()
    assert small.result() == real.result()
    assert flags(mini, small.status()) == flags(chess, real.status())
    assert small.castling_rights == real.castling_rights
    assert small.ep_square == real.ep_square


@pytest.mark.parametrize("seed", range(40))
def test_random_games_match_python_chess(seed):
    rng = random.Random(seed)
    real, small = chess.Board(), mini.Board()
    for _ in range(300):
        assert_same(real, small)
        if real.is_game_over():
            break
        move = rng.choice(sorted(real.legal_moves, key=lambda m: m.uci()))
        twin = mini.Move.from_uci(move.uci())
        assert small.is_capture(twin) == real.is_capture(move)
        assert small.is_en_passant(twin) == real.is_en_passant(move)
        assert small.is_castling(twin) == real.is_castling(move)
        assert small.is_kingside_castling(twin) == real.is_kingside_castling(move)
        assert small.parse_san(real.san(move)) == twin
        real.push(move)
        small.push(twin)


def perft(board, depth):
    if depth == 0:
        return 1
    total = 0
    for move in board.legal_moves:
        board.push(move)
        total += perft(board, depth - 1)
        board.pop()
    return total


@pytest.mark.parametrize(
    "fen, depth, nodes",
    [
        (mini.STARTING_FEN, 3, 8902),
        ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),
        ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 2, 264),
        ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 2, 1486),
    ],
)
def test_move_counts_of_known_positions(fen, depth, nodes):
    assert perft(mini.Board(fen), depth) == nodes


@pytest.mark.parametrize(
    "fen",
    [
        "8/8/8/8/8/8/8/8 w - - 0 1",
        "4k3/8/8/8/8/8/8/8 w - - 0 1",
        "4k3/8/8/8/3K4/8/8/4K3 w - - 0 1",
        "4k3/8/8/8/8/8/8/3PK3 w - - 0 1",
        "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1",
        "4k3/8/8/8/8/5n2/3n4/R3K2R w - - 0 1",
        "4k3/8/8/8/7b/8/8/r3K2r w - - 0 1",
        "4k3/8/8/8/8/8/8/r3K2r w - - 0 1",
        "4k3/8/4r3/8/8/8/4r3/4K3 w - - 0 1",
        "4k3/pppppppp/8/8/8/p7/PPPPPPPP/RNBQKBNR w KQ - 0 1",
        "QQQQkQQQ/QQQQQQQQ/QQ6/8/8/8/8/4K3 w - - 0 1",
        "4k3/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        "4k3/8/8/8/4P3/8/8/4K3 b - e3 0 1",
        "4k3/8/8/8/8/8/8/4K3 b - e3 0 1",
        "8/8/8/1k6/2P5/8/8/4K2B b - c3 0 1",
    ],
)
def test_position_problems_match_python_chess(fen):
    real, small = chess.Board(fen), mini.Board(fen)
    assert flags(mini, small.status()) == flags(chess, real.status())


@pytest.mark.parametrize("uci", ["e1g1", "e1c1", "e1e2", "a1a8", "e1f1", "h1h8"])
def test_pseudo_legal_matches_python_chess_when_castling_is_attacked(uci):
    fen = "4k3/8/8/8/8/8/5r2/R3K2R w KQ - 0 1"
    assert mini.Board(fen).is_pseudo_legal(mini.Move.from_uci(uci)) == chess.Board(fen).is_pseudo_legal(
        chess.Move.from_uci(uci)
    )


@pytest.mark.parametrize("san", ["Nf3", "e4", "Nc3", "a3"])
def test_san_from_the_start(san):
    assert mini.Board().parse_san(san).uci() == chess.Board().parse_san(san).uci()


@pytest.mark.parametrize("san", ["Ke2", "e5", "Nf6", "xx", "", "O-O"])
def test_bad_san_is_a_value_error(san):
    with pytest.raises(ValueError):
        mini.Board().parse_san(san)


def test_helpers_match_python_chess():
    for a in chess.SQUARES:
        assert mini.square_name(a) == chess.square_name(a)
        for b in chess.SQUARES:
            assert sorted(mini.between(a, b)) == list(chess.SquareSet(chess.between(a, b)))
            assert mini.square_distance(a, b) == chess.square_distance(a, b)
    assert mini.E1 == chess.E1 and mini.H8 == chess.H8


class Frozen(list):
    def __setitem__(self, index, value):
        raise AssertionError("the board was changed while only thinking about moves")


@pytest.mark.parametrize(
    "fen",
    [mini.STARTING_FEN, "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
     "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"],
)
def test_working_out_the_legal_moves_never_touches_the_board(fen):
    board = mini.Board(fen)
    board.squares = Frozen(board.squares)
    assert board.legal_moves
    board.status()
    board.is_checkmate()
    board.fen()
