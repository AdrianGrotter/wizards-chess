import pytest

from wizchess.grid import needs_edges, parse_command, render, starting_position


@pytest.mark.parametrize("text", ["A4 -> C2", "a4->c2", "A4 C2", "a4-c2", "a4 to c2", "  A4  ->  C2 "])
def test_move_spellings(text):
    assert parse_command(text) == ("move", "a4", "c2", False)


def test_move_forced_along_edges():
    assert parse_command("B1 -> C3 edges") == ("move", "b1", "c3", True)


def test_single_square_moves_the_head():
    assert parse_command("E4") == ("goto", "e4")


def test_put_keeps_the_piece_colour():
    assert parse_command("put E4 N") == ("put", "e4", "N")
    assert parse_command("put e5 q") == ("put", "e5", "q")


def test_remove_reset_clear():
    assert parse_command("remove E4") == ("remove", "e4")
    assert parse_command("reset") == ("reset",)
    assert parse_command("CLEAR") == ("clear",)


@pytest.mark.parametrize("text", ["I4 -> C2", "A9", "A4 -> A4", "jump", "A4 -> C2 fast", "put e4 x"])
def test_rejects_nonsense(text):
    with pytest.raises(ValueError):
        parse_command(text)


def test_starting_position():
    pieces = starting_position()
    assert len(pieces) == 32
    assert pieces["e1"] == "K" and pieces["d8"] == "q" and pieces["g1"] == "N" and pieces["a7"] == "p"


def test_knights_always_go_along_edges():
    assert needs_edges(starting_position(), "g1", "f3")


def test_clear_straight_path_goes_direct():
    assert not needs_edges(starting_position(), "e2", "e4")
    assert not needs_edges({"a1": "B"}, "a1", "h8")


def test_blocked_path_goes_along_edges():
    assert needs_edges(starting_position(), "a1", "a3")
    assert needs_edges({"a1": "B", "d4": "p"}, "a1", "h8")


def test_crooked_path_goes_along_edges():
    assert needs_edges({"b7": "p"}, "b7", "g1")


def test_render_shows_pieces_head_and_origin():
    pieces = starting_position()
    pieces["e4"] = pieces.pop("e2")
    lines = render(pieces, head="e4", came_from="e2").splitlines()
    assert lines[0] == "     A   B   C   D   E   F   G   H"
    assert lines[1] == " 8   r   n   b   q   k   b   n   r   8"
    assert lines[5] == " 4   .   .   .   .  [P]  .   .   .   4"
    assert lines[7] == " 2   P   P   P   P   o   P   P   P   2"
