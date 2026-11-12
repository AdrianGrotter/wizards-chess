import math

from .geometry import BOARD_EDGE_HIGH, BOARD_EDGE_LOW, on_board


def _sign(value):
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _toward_centre(value):
    return 1 if value < 3.5 else -1


def _clamp(value):
    return max(BOARD_EDGE_LOW, min(BOARD_EDGE_HIGH, value))


def _on_line(value):
    """Whether value lies on a line between squares (…, -0.5, 0.5, 1.5, …)."""
    return abs((value + 0.5) - round(value + 0.5)) < 1e-6


def route(start, end, via_edges=False):
    """Grid points the magnet passes through to drag a piece from start to end.

    With via_edges the piece leaves its square diagonally onto the lines
    between squares, travels along those lines, and enters the target
    diagonally, so it never passes over another square's centre. When the
    piece stays on its own file or rank, the detour bends toward the board's
    centre so it never runs along the outer edge.
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


def route_out(square, slot):
    """Grid points for dragging a piece from a square to a slot in a row beyond the board.

    The piece steps diagonally onto the lines between squares, follows a line
    to the board's edge on the row's side, runs along that edge, and steps
    straight out into its slot, between the pieces already parked there.
    Reverse the list to bring a parked piece back.
    """
    (f0, r0), (fs, rs) = square, slot
    toward_row = 1 if rs > r0 else -1
    edge = BOARD_EDGE_HIGH if toward_row > 0 else BOARD_EDGE_LOW
    sf = _sign(fs - f0) or _toward_centre(f0)
    leave = (f0 + 0.5 * sf, r0 + 0.5 * toward_row)
    path = [square, leave, (leave[0], edge), (fs, edge), slot]
    return [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]


def _line_toward(position, target):
    """The nearest line between squares from position, on target's side."""
    if _on_line(position):
        return position
    if target > position or (target == position and position < 3.5):
        return _clamp(math.floor(position) + 0.5)
    return _clamp(math.ceil(position) - 0.5)


def _line_beside(target, line):
    """The line next to target on the side facing line."""
    if _on_line(target):
        return target
    side = _sign(target - line)
    return target - 0.5 * side if side else line


def travel_route(start, end):
    """Grid points for moving the empty head from start to end.

    The head first steps onto the nearest line between squares, follows the
    lines, and only leaves them for the last diagonal step onto end, so it
    never passes straight under another piece.
    """
    start = (round(start[0], 6), round(start[1], 6))
    end = (float(end[0]), float(end[1]))
    if start == end:
        return [start]
    on_line = (_line_toward(start[0], end[0]), _line_toward(start[1], end[1]))
    near_end = (_line_beside(end[0], on_line[0]), _line_beside(end[1], on_line[1]))
    path = [start, on_line, (near_end[0], on_line[1]), near_end, end]
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

    def head_grid(self):
        head = self.machine.head
        return None if head is None else self.geometry.to_grid(head)

    def _check(self, points, keep_on_board):
        for point in points:
            if keep_on_board and not on_board(point):
                raise ValueError(
                    "That route would leave the board (at grid point %.1f, %.1f)." % tuple(point)
                )
            self.machine.check_reach(*self.geometry.to_mm(point))

    def path(self, step):
        if not step.leaves_board:
            return route(step.start, step.end, step.via_edges)
        if on_board(step.start):
            return route_out(step.start, step.end)
        return list(reversed(route_out(step.end, step.start)))

    def check(self, step):
        """Refuse a step before anything moves if any part of it is off the board or out of reach."""
        self._check(self.path(step), not step.leaves_board)

    def goto(self, point):
        """Move the head, magnet off, to a grid point along the lines between squares."""
        here = self.head_grid()
        path = [tuple(point)] if here is None else travel_route(here, point)[1:]
        self._check(path, keep_on_board=False)
        for p in path:
            x, y = self.geometry.to_mm(p)
            self.machine.move_to(x, y, self.travel_feed)

    def park(self):
        """Move the head, magnet off, to the machine's (0, 0) corner."""
        if self.machine.head is None:
            raise ValueError(
                "The head's position is unknown, so it can't be parked. Push it into its corner by hand."
            )
        corner = self.geometry.to_grid((0.0, 0.0))
        self.goto((_clamp(corner[0]), _clamp(corner[1])))
        self.machine.move_to(0, 0, self.travel_feed)
        self.machine.wait_until_idle()

    def run(self, step):
        path = self.path(step)
        self._check(path, not step.leaves_board)
        self.goto(path[0])
        try:
            self.machine.magnet(True)
            self.machine.dwell(self.grab_seconds)
            for point in path[1:]:
                x, y = self.geometry.to_mm(point)
                self.machine.move_to(x, y, self.drag_feed)
        except BaseException:
            try:
                self.machine.magnet(False)
            except Exception:
                pass
            raise
        self.machine.magnet(False)
        self.machine.dwell(self.grab_seconds)
        self.machine.wait_until_idle()
