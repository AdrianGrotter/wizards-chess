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


def test_same_file_route():
    assert route((4, 0), (4, 2), via_edges=True) == [(4, 0), (4.5, 0.5), (4.5, 1.5), (4, 2)]


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


def test_mover_releases_magnet_when_a_move_fails():
    machine = FakeMachine((300, 300), 1000, echo=False)
    mover = Mover(machine, Geometry((60, 60), (235, 235)), 3000, 1500)
    try:
        mover.run(Step((0, 0), (20, 0)))
    except ValueError:
        pass
    assert machine.lines[-1] == "M5"
