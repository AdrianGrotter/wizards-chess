import pytest

from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine
from wizchess.mover import Mover, Step, route, travel_route


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


def on_lines_except_ends(path):
    return all(f % 1 == 0.5 or r % 1 == 0.5 for f, r in path[1:-1])


def test_travel_between_squares_follows_the_lines():
    path = travel_route((4, 1), (4, 3))
    assert path == [(4, 1), (3.5, 1.5), (3.5, 2.5), (4, 3)]
    assert on_lines_except_ends(path)


def test_travel_from_the_parking_corner():
    path = travel_route((-0.91, -0.91), (2, 4))
    assert path == [(-0.91, -0.91), (-0.5, -0.5), (1.5, -0.5), (1.5, 3.5), (2, 4)]


def test_travel_to_a_line_point():
    assert travel_route((4, 3), (-0.5, -0.5)) == [(4, 3), (3.5, 2.5), (-0.5, 2.5), (-0.5, -0.5)]


def test_travel_to_where_the_head_already_is():
    assert travel_route((4, 3), (4, 3)) == [(4, 3)]


def make_mover(machine):
    return Mover(machine, Geometry((31, 31), (269, 31), (31, 269)), 3000, 1500)


def test_mover_grabs_drags_and_releases():
    machine = FakeMachine((300, 300), 1000, echo=False)
    machine.head = None
    make_mover(machine).run(Step((4, 1), (4, 3)))
    assert machine.lines == [
        "G53 G1 X167.00 Y65.00 F3000",
        "M3 S1000",
        "G4 P0.30",
        "G53 G1 X167.00 Y133.00 F1500",
        "M5",
        "G4 P0.30",
    ]


def test_head_travels_along_lines_to_the_piece():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = make_mover(machine)
    machine.head = mover.geometry.square_mm("e2")
    mover.goto((4, 3))
    assert machine.lines == ["G53 G1 X150.00 Y82.00 F3000", "G53 G1 X150.00 Y116.00 F3000", "G53 G1 X167.00 Y133.00 F3000"]
    assert machine.head == (167, 133)


def test_route_off_the_board_is_refused_before_anything_moves():
    machine = FakeMachine((300, 300), 1000, echo=False)
    with pytest.raises(ValueError, match="leave the board"):
        make_mover(machine).run(Step((7, 0), (8, 0)))
    assert machine.lines == []


def test_route_out_of_reach_is_refused_before_anything_moves():
    machine = FakeMachine((250, 250), 1000, echo=False)
    with pytest.raises(ValueError, match="outside the machine"):
        make_mover(machine).run(Step((0, 0), (7, 7)))
    assert machine.lines == []


def test_check_refuses_without_moving():
    machine = FakeMachine((300, 300), 1000, echo=False)
    with pytest.raises(ValueError):
        make_mover(machine).check(Step((7, 0), (8, 0)))
    assert machine.lines == []


def test_parking_beside_the_board_is_allowed_when_asked():
    machine = FakeMachine((300, 300), 1000, echo=False)
    make_mover(machine).run(Step((7, 0), (7.4, 0), leaves_board=True))
    assert "M5" in machine.lines


def test_park_goes_to_the_corner_along_the_lines():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = make_mover(machine)
    machine.head = mover.geometry.square_mm("e4")
    mover.park()
    assert machine.lines[-1] == "G53 G1 X0.00 Y0.00 F3000"
    assert machine.lines[0] == "G53 G1 X150.00 Y116.00 F3000"
    assert machine.head == (0, 0)


def test_park_with_unknown_head_is_refused():
    machine = FakeMachine((300, 300), 1000, echo=False)
    machine.head = None
    with pytest.raises(ValueError, match="unknown"):
        make_mover(machine).park()


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


def test_stop_forgets_the_head_position():
    machine = FakeMachine((300, 300), 1000, echo=False)
    machine.stop()
    assert machine.head is None


def test_route_out_runs_along_the_edge_and_steps_straight_into_the_slot():
    from wizchess.mover import route_out

    assert route_out((3, 4), (3.5, 8)) == [(3, 4), (3.5, 4.5), (3.5, 7.5), (3.5, 8)]
    assert route_out((4, 0), (1.0, -1)) == [(4, 0), (3.5, -0.5), (1.0, -0.5), (1.0, -1)]
    assert route_out((0, 6), (7.5, 8)) == [(0, 6), (0.5, 6.5), (0.5, 7.5), (7.5, 7.5), (7.5, 8)]


def test_every_slot_is_reachable_on_the_real_layout():
    from wizchess.game import Graveyard

    machine = FakeMachine((300, 320), 1000, echo=False)
    mover = Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 3000, 1500)
    graveyard = Graveyard({"white": -1, "black": 8})
    for color in ("white", "black"):
        for slot in graveyard.slots[color]:
            for square in [(0, 0), (7, 7), (3, 3)]:
                mover.check(Step(square, slot, leaves_board=True))
                mover.check(Step(slot, square, leaves_board=True))


def test_at_speed_applies_to_travel_and_drag_until_restored():
    machine = FakeMachine((300, 300), 1000, echo=False)
    machine.head = None
    mover = make_mover(machine)
    restore = mover.at_speed(1500)
    mover.run(Step((4, 1), (4, 3)))
    restore()
    assert [l.split()[-1] for l in machine.lines if l.startswith("G53")] == ["F1500", "F1500"]
    assert (mover.travel_feed, mover.drag_feed) == (3000, 1500)
