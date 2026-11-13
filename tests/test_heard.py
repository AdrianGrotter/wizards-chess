import chess
import pytest

from wizchess.heard import Heard, Interpreter, words


def state(moves="", rules=True, question=None):
    board = chess.Board()
    for san in moves.split():
        board.push_san(san)
    legal = {}
    for move in board.legal_moves:
        targets = legal.setdefault(chess.square_name(move.from_square), [])
        if chess.square_name(move.to_square) not in targets:
            targets.append(chess.square_name(move.to_square))
    return {
        "pieces": {chess.square_name(sq): p.symbol() for sq, p in board.piece_map().items()},
        "moves": legal if rules else {},
        "rules": rules,
        "question": question,
    }


def hear(text, moves="", **kwargs):
    return Interpreter().hear(text, state(moves, **kwargs))


@pytest.mark.parametrize("text, expected", [
    ("E2, E4.", ["e2", "e4"]),
    ("a two a four", ["a2", "a4"]),
    ("alpha 2 to alpha 4", ["a2", "to", "a4"]),
    ("Knight to f3.", ["knight", "to", "f3"]),
    ("G1F3.", ["g1", "f3"]),
    ("Knight, bd2.", ["knight", "b", "d2"]),
    ("be for", ["b4"]),
    ("a 4 hour drive", ["a4", "hour", "drive"]),
])
def test_words(text, expected):
    assert words(text) == expected


@pytest.mark.parametrize("text, moves, command", [
    ("e2 e4", "", "e2 e4"),
    ("E2 to E4.", "", "e2 e4"),
    ("Knight to f3.", "", "g1 f3"),
    ("night f3", "", "g1 f3"),
    ("pawn to d4", "", "d2 d4"),
    ("Move on to d4.", "", "d2 d4"),
    ("e4", "", "e2 e4"),
    ("pawn takes d5", "e4 d5", "e4 d5"),
    ("takes d5", "e4 d5", "e4 d5"),
    ("pawn takes pawn", "e4 d5", "e4 d5"),
    ("bishop takes c6", "e4 e5 Nf3 Nc6 Bb5 a6", "b5 c6"),
    ("castle kingside", "e4 e5 Nf3 Nc6 Bc4 Bc5", "e1 g1"),
    ("castle", "e4 e5 Nf3 Nc6 Bc4 Bc5", "e1 g1"),
    ("castle queen side", "d4 d5 Nc3 Nc6 Bf4 Bf5 Qd2 Qd7", "e1 c1"),
    ("knight b d2", "d4 d5 Nf3 Nf6", "b1 d2"),
    ("Knight, bd2.", "d4 d5 Nf3 Nf6", "b1 d2"),
    ("b takes a8 promote to knight", "a4 b5 axb5 a6 bxa6 Bb7 axb7 Nc6", "b7 a8 n"),
    ("pawn takes a8", "a4 b5 axb5 a6 bxa6 Bb7 axb7 Nc6", "b7 a8 q"),
])
def test_moves(text, moves, command):
    assert hear(text, moves) == Heard("command", command)


@pytest.mark.parametrize("text", [
    "", "Thank you.", "I waited for a four hour drive", "what a nice knight", "yes", "no way",
    "he took my queen yesterday", "the", "queen",
])
def test_chatter_is_ignored(text):
    assert hear(text) is None


def test_move_is_said_back():
    assert hear("knight to f3").spoken == "Knight to F3."
    assert hear("pawn takes d5", "e4 d5").spoken == "Pawn takes pawn on D5."
    assert hear("castle short", "e4 e5 Nf3 Nc6 Bc4 Bc5").spoken == "Castling kingside."


def test_impossible_move_with_a_named_piece_gets_a_reason():
    heard = hear("knight to e4")
    assert heard.kind == "say" and heard.spoken == "No knight can go to E4."


def test_two_squares_go_to_the_board_even_when_illegal():
    assert hear("e2 e5") == Heard("command", "e2 e5")


def test_two_knights_lead_to_a_question_and_an_answer():
    listener = Interpreter()
    position = state("d4 d5 Nf3 Nf6")
    asked = listener.hear("knight to d2", position)
    assert asked.kind == "say" and asked.spoken == "Which knight: the one on B1 or F3?"
    assert listener.hear("the one on f3", position) == Heard("command", "f3 d2")
    assert listener.choices is None


def test_never_mind_drops_the_question():
    listener = Interpreter()
    position = state("d4 d5 Nf3 Nf6")
    listener.hear("knight to d2", position)
    assert listener.hear("never mind", position).kind == "say"
    assert listener.hear("f3", position) is None


def test_board_question_is_answered_by_yes_and_no():
    question = {"text": "Is the head in its corner?", "yes": "Yes", "no": "No"}
    assert hear("Yes.", question=question) == Heard("answer", True)
    assert hear("nope", question=question) == Heard("answer", False)
    assert hear("knight to f3", question=question) is None


def test_stop_always_counts():
    assert hear("Stop!") == Heard("stop")
    assert hear("stop it", question={"text": "?", "yes": "Y", "no": "N"}) == Heard("stop")
    assert hear("don't stop believing") is None


def test_new_game_needs_a_yes():
    listener = Interpreter()
    assert listener.hear("New game.", state()).kind == "say"
    assert listener.hear("yes", state()) == Heard("command", "reset")
    assert listener.hear("new game", state()).kind == "say"
    assert listener.hear("no", state()).spoken == "Okay, leaving it."
    assert listener.hear("yes", state()) is None


def test_rules_off_takes_only_two_squares():
    assert hear("a1 a8", rules=False) == Heard("command", "a1 a8")
    assert hear("knight to f3", rules=False) is None
