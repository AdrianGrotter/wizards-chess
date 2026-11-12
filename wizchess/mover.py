from .geometry import on_board


def _sign(value):
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _toward_centre(value):
    return 1 if value < 3.5 else -1


def route(start, end, via_edges=False):
    """Grid points the magnet passes through to drag a piece from start to end.

    With via_edges the piece leaves its square diagonally onto the lines
    between squares, travels along those lines, and enters the target
    diagonally, so it never passes over another square's centre.
    """
    if not via_edges:
        return [start, end]
    (f0, r0), (f1, r1) = start, end
    sf = _sign(f1 - f0) or _toward_centre(f0)
    sr = _sign(r1 - r0) or _toward_centre(r0)
    leave = (f0 + 0.5 * sf, r0 + 0.5 * sr)
    arrive_f = f1 - 0.5 * sf if f1 != f0 else leave[0]
    arrive_r = r1 - 0.5 * sr if r1 != r0 else leave[1]
    path = [start, leave, (arrive_f, leave[1]), (arrive_f, arrive_r), end]
    return [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]


class Step:
    """Drag one piece from one grid point to another.

    leaves_board allows the route outside the board's edges, for parking
    captured pieces beside it.
    """

    def __init__(self, start, end, via_edges=False, leaves_board=False):
        self.start = (float(start[0]), float(start[1]))
        self.end = (float(end[0]), float(end[1]))
        self.via_edges = via_edges
        self.leaves_board = leaves_board

    def __eq__(self, other):
        return (
            isinstance(other, Step)
            and self.start == other.start
            and self.end == other.end
            and self.via_edges == other.via_edges
            and self.leaves_board == other.leaves_board
        )

    def __repr__(self):
        return "Step(%r, %r, via_edges=%r, leaves_board=%r)" % (
            self.start, self.end, self.via_edges, self.leaves_board
        )


class Mover:
    def __init__(self, machine, geometry, travel_feed, drag_feed, grab_seconds=0.3):
        self.machine = machine
        self.geometry = geometry
        self.travel_feed = travel_feed
        self.drag_feed = drag_feed
        self.grab_seconds = grab_seconds

    def _check(self, points, leaves_board=False):
        """Refuse a path before any of it runs if a point is off the board or out of reach."""
        for point in points:
            if not leaves_board and not on_board(point):
                raise ValueError("The route %s leaves the board at grid point %s" % (points, point))
            self.machine.check_reach(*self.geometry.to_mm(point))

    def goto(self, point):
        self._check([point])
        x, y = self.geometry.to_mm(point)
        self.machine.move_to(x, y, self.travel_feed)

    def park(self):
        """Move the head, magnet off, to the machine's (0, 0) corner."""
        self.machine.move_to(0, 0, self.travel_feed)
        self.machine.wait_until_idle()

    def run(self, step):
        path = route(step.start, step.end, step.via_edges)
        self._check(path, step.leaves_board)
        self.goto(path[0])
        try:
            self.machine.magnet(True)
            self.machine.dwell(self.grab_seconds)
            for point in path[1:]:
                x, y = self.geometry.to_mm(point)
                self.machine.move_to(x, y, self.drag_feed)
        finally:
            self.machine.magnet(False)
        self.machine.dwell(self.grab_seconds)
        self.machine.wait_until_idle()
