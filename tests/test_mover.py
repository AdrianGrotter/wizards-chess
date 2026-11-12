import pytest

from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine
from wizchess.mover import Mover, Step, route


def test_direct_route():
    assert route((4, 1), (4, 3)) == [(4, 1), (4, 3)]


def test_knight_route_stays_between_squares():
    path = route((1, 0), (2, 2), via_edges=True)
    assert path == [(1, 0), (1.5, 0.5), (1.5, 1.5), (2, 2)]
    for f, r in path[1:-1]:
        assert f % 1 == 0.5 and r % 1 == 0.5


def test_castling_rook_route_passes_beside_the_king():
    assert route((7, 0), (5, 0), via_edges=True) == [(7, 0), (6.5, 0.5), (5.5, 0.5), (5, 0)]


def test_same_file_route_turns_toward_the_centre():
    assert route((1, 0), (1, 2), via_edges=True) == [(1, 0), (1.5, 0.5), (1.5, 1.5), (1, 2)]
    assert route((7, 0), (7, 2), via_edges=True) == [(7, 0), (6.5, 0.5), (6.5, 1.5), (7, 2)]


def test_black_castling_rook_stays_inside_the_board():
    assert route((7, 7), (5, 7), via_edges=True) == [(7, 7), (6.5, 6.5), (5.5, 6.5), (5, 7)]


def test_route_to_graveyard():
    assert route((3, 3), (-1, 0), via_edges=True) == [
        (3, 3), (2.5, 2.5), (-0.5, 2.5), (-0.5, 0.5), (-1, 0)
    ]


def test_mover_grabs_drags_and_releases():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = Mover(machine, Geometry((60, 60), (235, 235)), travel_feed=3000, drag_feed=1500)
    mover.run(Step((4, 1), (4, 3)))
    assert machine.lines == [
        "G53 G1 X160.00 Y85.00 F3000",
        "M3 S1000",
        "G4 P0.30",
        "G53 G1 X160.00 Y135.00 F1500",
        "M5",
        "G4 P0.30",
    ]


def make_mover(machine):
    return Mover(machine, Geometry((31, 31), (269, 269)), 3000, 1500)


def test_route_off_the_board_is_refused_before_anything_moves():
    machine = FakeMachine((300, 300), 1000, echo=False)
    with pytest.raises(ValueError, match="leaves the board"):
        make_mover(machine).run(Step((7, 0), (8, 0)))
    assert machine.lines == []


def test_route_out_of_reach_is_refused_before_anything_moves():
    machine = FakeMachine((250, 250), 1000, echo=False)
    with pytest.raises(ValueError, match="outside the machine"):
        make_mover(machine).run(Step((0, 0), (7, 7)))
    assert machine.lines == []


def test_parking_beside_the_board_is_allowed_when_asked():
    machine = FakeMachine((300, 300), 1000, echo=False)
    make_mover(machine).run(Step((7, 0), (7.6, 0), leaves_board=True))
    assert "M5" in machine.lines


class FailingMachine(FakeMachine):
    def move_to(self, x, y, feed):
        if self.lines.count("M3 S1000"):
            raise RuntimeError("lost connection")
        super().move_to(x, y, feed)


def test_mover_releases_magnet_when_a_drag_fails():
    machine = FailingMachine((300, 300), 1000, echo=False)
    with pytest.raises(RuntimeError):
        make_mover(machine).run(Step((0, 0), (0, 2)))
    assert machine.lines[-1] == "M5"


def test_park_returns_the_head_to_the_corner_with_the_magnet_off():
    machine = FakeMachine((300, 300), 1000, echo=False)
    make_mover(machine).park()
    assert machine.lines == ["G53 G1 X0.00 Y0.00 F3000"]
