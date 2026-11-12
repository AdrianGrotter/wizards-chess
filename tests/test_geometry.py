import pytest

from wizchess.geometry import Geometry, parse_square, square_name


def test_parse_square():
    assert parse_square("a1") == (0, 0)
    assert parse_square("H8") == (7, 7)
    assert parse_square("e4") == (4, 3)
    assert square_name((4, 3)) == "e4"


@pytest.mark.parametrize("bad", ["i1", "a9", "a0", "e", "e44"])
def test_parse_square_rejects_bad_names(bad):
    with pytest.raises(ValueError):
        parse_square(bad)


def square_board():
    return Geometry(a1=(31, 31), h1=(269, 31), a8=(31, 269))


def test_corners_land_on_calibration_points():
    g = square_board()
    assert g.square_mm("a1") == (31, 31)
    assert g.square_mm("h1") == (269, 31)
    assert g.square_mm("a8") == (31, 269)
    assert g.square_mm("h8") == (269, 269)


def test_squares_are_evenly_spaced():
    g = square_board()
    assert g.square_mm("b1") == (65, 31)
    assert g.square_mm("a2") == (31, 65)
    assert g.to_mm((0.5, 0.5)) == (48, 48)


def test_files_along_y():
    g = Geometry(a1=(31, 31), h1=(31, 269), a8=(269, 31))
    assert g.square_mm("b1") == (31, 65)
    assert g.square_mm("a2") == (65, 31)


def test_rotated_board_is_hit_dead_centre():
    # Board turned by about 1 degree: h1 sits 4 mm higher than a1.
    g = Geometry(a1=(31, 31), h1=(269, 35), a8=(27, 269))
    x, y = g.square_mm("h8")
    assert (round(x, 6), round(y, 6)) == (265, 273)
    x, y = g.square_mm("e4")
    assert abs(x - (31 + 4 * 34 - 3 * 4 / 7)) < 1e-9
    assert abs(y - (31 + 3 * 34 + 4 * 4 / 7)) < 1e-9


def test_to_grid_inverts_to_mm():
    g = Geometry(a1=(31, 31), h1=(269, 35), a8=(27, 269))
    for point in [(0, 0), (7, 7), (3.5, 2.5), (-0.5, 7.5)]:
        f, r = g.to_grid(g.to_mm(point))
        assert abs(f - point[0]) < 1e-9 and abs(r - point[1]) < 1e-9


def test_square_at():
    g = square_board()
    assert g.square_at((167, 133)) == "e4"
    assert g.square_at((167.5, 133)) == "e4"
    assert g.square_at((184, 133)) is None
    assert g.square_at((0, 0)) is None


def test_calibration_points_on_one_line_are_refused():
    with pytest.raises(ValueError, match="one line"):
        Geometry(a1=(31, 31), h1=(269, 31), a8=(150, 31))


def test_old_two_point_config_still_works():
    g = Geometry.from_config({"a1": [31, 31], "h8": [269, 269], "files_along": "y"})
    assert g.square_mm("b1") == (31, 65)
