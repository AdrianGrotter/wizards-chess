import pytest

from wizchess.grid import parse_command, render


@pytest.mark.parametrize("text", ["A4 -> C2", "a4->c2", "A4 C2", "a4c2", "a4-c2", "a4 to c2", "  A4  ->  C2 "])
def test_move_spellings(text):
    assert parse_command(text) == ("move", "a4", "c2", None, False)


def test_promotion_choice():
    assert parse_command("E7 -> E8 N") == ("move", "e7", "e8", "n", False)
    assert parse_command("e7e8=q") == ("move", "e7", "e8", "q", False)


def test_single_square_moves_the_head():
    assert parse_command("E4") == ("goto", "e4", False)


def test_put_keeps_the_piece_colour():
    assert parse_command("put E4 N") == ("put", "e4", "N")
    assert parse_command("put e5 q") == ("put", "e5", "q")


def test_remove_reset_clear():
    assert parse_command("remove E4") == ("remove", "e4")
    assert parse_command("reset") == ("reset", "pieces")
    assert parse_command("reset grid") == ("reset", "grid")
    assert parse_command("CLEAR") == ("clear",)
    assert parse_command("park") == ("park",)


@pytest.mark.parametrize(
    "text, message",
    [
        ("I4 -> C2", "I4 is not on the board: columns go from A to H."),
        ("A9", "A9 is not on the board: rows go from 1 to 8."),
        ("A0", "A0 is not on the board: rows go from 1 to 8."),
        ("e44", "E44 is not on the board: rows go from 1 to 8."),
        ("A4 -> 44", "'44' is not a square."),
        ("A4 A4", "A4 A4 starts and ends on the same square."),
        ("jump", "Unknown command 'jump'."),
        ("A4 -> C2 fast", "Unexpected 'fast' after the move. Only 'slow' or a promotion piece"),
        ("A4 -> C2 k", "Unexpected 'k' after the move."),
        ("put e4 x", "'x' is not a piece."),
        ("put e4", "Use put with a square and a piece"),
        ("remove", "Use remove with one square"),
        ("reset now", "Use reset on its own, or reset grid"),
        ("park now", "'park' doesn't take anything after it."),
    ],
)
def test_clear_error_messages(text, message):
    with pytest.raises(ValueError) as error:
        parse_command(text)
    assert str(error.value).startswith(message)


def test_render_shows_pieces_head_and_origin():
    pieces = {"e8": "k", "a8": "r", "e4": "P", "a2": "P", "e1": "K"}
    lines = render(pieces, head="e4", came_from="e2").splitlines()
    assert lines[0] == "     A   B   C   D   E   F   G   H"
    assert lines[1] == " 8   r   .   .   .   k   .   .   .   8"
    assert lines[5] == " 4   .   .   .   .  [P]  .   .   .   4"
    assert lines[7] == " 2   P   .   .   .   o   .   .   .   2"


def test_turn_and_unlock():
    assert parse_command("turn Black") == ("turn", "black")
    assert parse_command("unlock") == ("unlock",)
    with pytest.raises(ValueError, match="Use turn with white or black"):
        parse_command("turn red")


def test_rules_on_off():
    assert parse_command("rules off") == ("rules", "off")
    assert parse_command("Rules ON") == ("rules", "on")
    with pytest.raises(ValueError, match="Use rules with on or off"):
        parse_command("rules")


def test_slow_moves():
    assert parse_command("B1 C3 slow") == ("move", "b1", "c3", None, True)
    assert parse_command("e7 e8 n SLOW") == ("move", "e7", "e8", "n", True)
    assert parse_command("e7 e8 slow n") == ("move", "e7", "e8", "n", True)
    assert parse_command("A4 slow") == ("goto", "a4", True)
