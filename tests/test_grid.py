import pytest

from wizchess.grid import parse_command, render


@pytest.mark.parametrize("text", ["A4 -> C2", "a4->c2", "A4 C2", "a4-c2", "a4 to c2", "  A4  ->  C2 "])
def test_move_spellings(text):
    assert parse_command(text) == ("move", "a4", "c2", False)


def test_move_via_edges():
    assert parse_command("B1 -> C3 edges") == ("move", "b1", "c3", True)


def test_single_square_moves_the_head():
    assert parse_command("E4") == ("goto", "e4")


@pytest.mark.parametrize("text", ["I4 -> C2", "A9", "A4 -> A4", "jump", "A4 -> C2 fast"])
def test_rejects_nonsense(text):
    with pytest.raises(ValueError):
        parse_command(text)


def test_render_marks_head_and_last_move():
    lines = render(head="c2", start="a4", end="c2").splitlines()
    assert lines[0] == "    A  B  C  D  E  F  G  H"
    assert lines[5] == " 4  o  .  .  .  .  .  .  .   4"
    assert lines[7] == " 2  .  .  @  .  .  .  .  .   2"
