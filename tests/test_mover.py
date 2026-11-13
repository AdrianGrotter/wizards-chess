import pytest

from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine
from wizchess.mover import Mover, Step, is_clear, route, route_out


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


def test_head_travels_straight_to_the_piece_even_under_other_pieces():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = make_mover(machine)
    machine.head = mover.geometry.square_mm("e2")
    mover.goto((4, 3), occupied={(4, 2)})
    assert machine.lines == ["G53 G1 X167.00 Y133.00 F3000"]
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


def test_park_goes_straight_to_the_corner():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = make_mover(machine)
    machine.head = mover.geometry.square_mm("e4")
    mover.park()
    assert machine.lines == ["G53 G1 X0.00 Y0.00 F3000"]
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


def test_slow_drag_leaves_travel_at_full_speed():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = make_mover(machine)
    machine.head = mover.geometry.square_mm("a1")
    restore = mover.dragging_at(500)
    mover.run(Step((4, 1), (4, 3)))
    restore()
    magnet_on = machine.lines.index("M3 S1000")
    travel = [l.split()[-1] for l in machine.lines[:magnet_on] if l.startswith("G53")]
    drag = [l.split()[-1] for l in machine.lines[magnet_on:] if l.startswith("G53")]
    assert set(travel) == {"F3000"} and drag == ["F500"]
    assert mover.drag_feed == 1500


def test_is_clear_keeps_half_a_square_from_other_pieces():
    assert is_clear([(4, 1), (4, 3)], {(3, 1), (5, 1), (4, 0)})
    assert not is_clear([(4, 1), (4, 3)], {(4, 2)})
    assert not is_clear([(6, 0), (5, 2)], {(6, 1)})
    assert is_clear([(3, 0), (7, 4)], {(4, 0), (5, 1)})


def test_auto_route_goes_straight_when_clear_and_through_gutters_when_blocked():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = make_mover(machine)
    knight = Step((6, 0), (5, 2), via_edges=None)
    assert mover.path(knight, occupied=set()) == [(6, 0), (5, 2)]
    assert mover.path(knight, occupied={(6, 1)}) == route((6, 0), (5, 2), via_edges=True)
    assert mover.path(knight) == route((6, 0), (5, 2), via_edges=True)


START = {(float(f), float(r)) for f in range(8) for r in (0, 1, 6, 7)}


def real_mover():
    machine = FakeMachine((300, 320), 1000, echo=False)
    return Mover(machine, Geometry((34.5, 44.5), (265.5, 44.5), (34.5, 275.5)), 3000, 1500)


def test_first_captured_piece_leaves_round_the_side_past_nothing():
    others = (START - {(3.0, 6.0), (4.0, 1.0)}) | {(4.0, 3.0)}
    path = real_mover().path(Step((3, 4), (3.5, 8), leaves_board=True), others)
    assert path[0] == (3, 4) and path[-1] == (3.5, 8)
    assert is_clear(path, others, 1.0)
    assert min(f for f, _ in path) < -0.5 or max(f for f, _ in path) > 7.5


def test_captured_piece_goes_round_pieces_already_parked():
    parked = {(3.5, 8.0), (3.0, 8.0)}
    others = (START - {(3.0, 6.0)}) | parked
    path = real_mover().path(Step((0, 4), (4.0, 8), leaves_board=True), others)
    assert path[-1] == (4.0, 8)
    assert is_clear(path, others)
    assert path[-2][0] > 4.0


def test_captured_piece_squeezes_through_when_the_machine_has_no_room_beside_the_board():
    machine = FakeMachine((300, 320), 1000, echo=False)
    mover = Mover(machine, Geometry((18, 44.5), (282, 44.5), (18, 275.5)), 3000, 1500)
    others = START - {(3.0, 6.0)}
    path = mover.path(Step((3, 4), (3.5, 8), leaves_board=True), others)
    assert path[-1] == (3.5, 8)
    assert is_clear(path, others)
    for point in path:
        machine.check_reach(*mover.geometry.to_mm(point))


def test_parked_piece_comes_back_by_a_quiet_route_too():
    others = START - {(3.0, 6.0)}
    path = real_mover().path(Step((3.5, 8), (3, 4), leaves_board=True), others)
    assert path[0] == (3.5, 8) and path[-1] == (3, 4)
    assert is_clear(path, others, 1.0)


def test_slot_off_the_half_square_lattice_uses_the_edge_route():
    path = real_mover().path(Step((3, 4), (3.3, 8), leaves_board=True), START)
    assert path == route_out((3.0, 4.0), (3.3, 8.0))


def centring_mover(radius, travel=(300, 320), a1=(34.5, 44.5)):
    machine = FakeMachine(travel, 1000, echo=False)
    geometry = Geometry(a1, (a1[0] + 231, a1[1]), (a1[0], a1[1] + 231))
    return machine, Mover(machine, geometry, 3000, 6000, centring_mm=radius)


def moves_of(machine):
    out = []
    for line in machine.lines:
        if line.startswith("G53"):
            x, y, feed = line.split()[2:]
            out.append((float(x[1:]), float(y[1:]), int(feed[1:])))
    return out


def test_drag_ends_with_a_spiral_that_closes_on_the_target():
    machine, mover = centring_mover(4)
    mover.run(Step((4, 1), (4, 3)))
    moves = moves_of(machine)
    target = (166.5, 143.5)
    assert moves[1] == target + (6000,)
    spiral = moves[2:]
    assert len(spiral) == 31 and spiral[-1] == target + (2400,)
    assert spiral[0] == (166.5, 147.5, 2400)
    radii = [((x - target[0]) ** 2 + (y - target[1]) ** 2) ** 0.5 for x, y, _ in spiral]
    assert radii == sorted(radii, reverse=True) and radii[0] == pytest.approx(4)
    assert machine.lines[-2] == "M5"
    assert machine.head == target


def test_a_trailing_piece_ends_close_to_the_target_whatever_the_friction():
    for lag in (0, 0.5, 1, 2, 3, 4):
        machine, mover = centring_mover(4)
        mover.run(Step((4, 1), (4, 3)))
        moves = moves_of(machine)
        px, py = moves[0][:2]
        for (ax, ay, _), (bx, by, _) in zip(moves, moves[1:]):
            for i in range(1, 201):
                mx, my = ax + (bx - ax) * i / 200, ay + (by - ay) * i / 200
                gap = ((mx - px) ** 2 + (my - py) ** 2) ** 0.5
                if gap > lag:
                    px, py = mx - (mx - px) * lag / gap, my - (my - py) * lag / gap
        missed = ((px - 166.5) ** 2 + (py - 143.5) ** 2) ** 0.5
        assert missed < 0.7, "a piece trailing by %s mm ends %.2f mm off" % (lag, missed)


def test_spiral_stays_within_the_machines_reach():
    machine, mover = centring_mover(5, a1=(2, 44.5))
    mover.run(Step((1, 0), (0, 0)))
    assert min(x for x, _, _ in moves_of(machine)) == 0.0


def test_no_spiral_unless_asked_for():
    machine, mover = centring_mover(0)
    mover.run(Step((4, 1), (4, 3)))
    assert len(moves_of(machine)) == 2
