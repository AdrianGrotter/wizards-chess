import pytest

from wizchess.geometry import Geometry, parse_square


def test_parse_square():
    assert parse_square("a1") == (0, 0)
    assert parse_square("H8") == (7, 7)
    assert parse_square("e4") == (4, 3)


@pytest.mark.parametrize("bad", ["i1", "a9", "a0", "e", "e44"])
def test_parse_square_rejects_bad_names(bad):
    with pytest.raises(ValueError):
        parse_square(bad)


def test_corners_land_on_calibration_points():
    g = Geometry(a1=(60, 60), h8=(235, 235))
    assert g.square_mm("a1") == (60, 60)
    assert g.square_mm("h8") == (235, 235)


def test_squares_are_evenly_spaced():
    g = Geometry(a1=(60, 60), h8=(235, 235))
    assert g.square_mm("b1") == (85, 60)
    assert g.square_mm("a2") == (60, 85)
    assert g.to_mm((0.5, 0.5)) == (72.5, 72.5)


def test_board_turned_so_files_run_along_y():
    g = Geometry(a1=(60, 60), h8=(235, 235), files_along="y")
    assert g.square_mm("b1") == (60, 85)
    assert g.square_mm("a2") == (85, 60)


def test_board_mirrored():
    g = Geometry(a1=(235, 60), h8=(60, 235))
    assert g.square_mm("b1") == (210, 60)
