import heapq

from .geometry import BOARD_EDGE_HIGH, BOARD_EDGE_LOW, on_board


# Grid points this close together (in squares) count as the same place. The
# ESP32 computes with single-precision floats, which are only good to about
# six digits.
TOLERANCE = 1e-4


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


# A moving piece or the empty head keeps at least this far (in squares) from
# the centre of every other piece; half a square is the gap a piece has when
# it passes between two neighbours along a gutter.
CLEARANCE = 0.5


def _distance_to_segment(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length))
    cx, cy = ax + t * dx, ay + t * dy
    return ((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5


def is_clear(path, occupied, clearance=CLEARANCE):
    """Whether every leg of path keeps clearance away from every occupied grid point."""
    return all(
        _distance_to_segment(p, a, b) >= clearance - TOLERANCE
        for a, b in zip(path, path[1:])
        for p in occupied
    )


# quiet_route works on a lattice of half squares, which holds every square
# centre, every gutter and every parking slot. LATTICE_SPAN reaches two
# squares beyond the board on every side.
LATTICE_SPAN = range(-4, 19)

# The search numbers the lattice points, with a ring of closed points around
# them so a step off the lattice never lands on another row. It counts in
# whole numbers only, because on the ESP32 every fraction costs memory.
_WIDTH = len(LATTICE_SPAN) + 2
_OFFSET = 1 - LATTICE_SPAN[0]
_STRAIGHT = (_WIDTH, -_WIDTH, 1, -1)
_DIAGONAL = ((_WIDTH, 1), (_WIDTH, -1), (-_WIDTH, 1), (-_WIDTH, -1))

# What passing a piece adds to the cost of a lattice point, by the squared
# distance between them in half squares: half a square away, a gutter corner
# away, a whole square away. Further away costs nothing. A plain half-square
# step costs 100.
CROWDING = {1: 600, 2: 250, 4: 50}

# A leg this far (in squares) from every piece disturbs nothing.
UNDISTURBED = 1.0


def _half_squares(point):
    """point counted in half squares, or None when it lies off the lattice."""
    x, y = point[0] * 2, point[1] * 2
    hx, hy = int(round(x)), int(round(y))
    if abs(x - hx) > TOLERANCE or abs(y - hy) > TOLERANCE:
        return None
    return (hx, hy)


def _straighten(path, occupied):
    """path with corners cut wherever the shortcut stays UNDISTURBED."""
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not is_clear([path[i], path[j]], occupied, UNDISTURBED):
            j -= 1
        out.append(path[j])
        i = j
    return out


def quiet_route(start, end, occupied, lattice):
    """Grid points for dragging a piece from start to end while disturbing other pieces least.

    Pieces pull on each other, so the route weighs its length against how
    close it passes to every piece in occupied: a longer way round through
    empty space beats a short squeeze between pieces. lattice holds the
    points, in half squares, that the machine can reach. Returns None when
    an end or a piece lies off the lattice, or when no route exists.
    """
    a, b = _half_squares(start), _half_squares(end)
    pieces = [_half_squares(p) for p in occupied]
    if a is None or b is None or None in pieces:
        return None
    size = _WIDTH * _WIDTH
    is_open = bytearray(size)
    for hx, hy in lattice:
        is_open[(hx + _OFFSET) * _WIDTH + hy + _OFFSET] = 1
    crowding = [0] * size
    blocked = []
    for piece in pieces:
        if piece == a or piece == b:
            continue
        blocked.append(piece)
        px, py = piece[0] + _OFFSET, piece[1] + _OFFSET
        if 0 <= px < _WIDTH and 0 <= py < _WIDTH:
            is_open[px * _WIDTH + py] = 0
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                weight = CROWDING.get(dx * dx + dy * dy)
                if weight and 0 <= px + dx < _WIDTH and 0 <= py + dy < _WIDTH:
                    crowding[(px + dx) * _WIDTH + py + dy] += weight

    first = (a[0] + _OFFSET) * _WIDTH + a[1] + _OFFSET
    last = (b[0] + _OFFSET) * _WIDTH + b[1] + _OFFSET
    if not (is_open[first] and is_open[last]):
        return None
    last_x, last_y = divmod(last, _WIDTH)
    best = [1 << 29] * size
    came_from = [0] * size
    done = bytearray(size)
    best[first] = 0
    # Each queue entry packs an estimate of the whole route's cost (above
    # the low ten bits) with the point's number (in them).
    queue = [first]
    while queue:
        node = heapq.heappop(queue) & 1023
        if done[node]:
            continue
        done[node] = 1
        if node == last:
            break
        cost = best[node]
        here = crowding[node]
        for diagonal in (0, 1):
            for move in _DIAGONAL if diagonal else _STRAIGHT:
                if diagonal:
                    if not (is_open[node + move[0]] and is_open[node + move[1]]):
                        continue
                    following = node + move[0] + move[1]
                else:
                    following = node + move
                if not is_open[following] or done[following]:
                    continue
                step = 200 + here + crowding[following]
                reached = cost + (step * 141 // 200 if diagonal else step // 2)
                if reached < best[following]:
                    best[following] = reached
                    came_from[following] = node
                    dx, dy = divmod(following, _WIDTH)
                    dx, dy = abs(dx - last_x), abs(dy - last_y)
                    to_go = 100 * max(dx, dy) + 41 * min(dx, dy)
                    heapq.heappush(queue, ((reached + to_go) << 10) | following)
    if not done[last]:
        return None

    numbers = [last]
    while numbers[-1] != first:
        numbers.append(came_from[numbers[-1]])
    numbers.reverse()
    nodes = [(n // _WIDTH - _OFFSET, n % _WIDTH - _OFFSET) for n in numbers]
    corners = [
        n for i, n in enumerate(nodes)
        if i in (0, len(nodes) - 1)
        or (n[0] - nodes[i - 1][0], n[1] - nodes[i - 1][1]) != (nodes[i + 1][0] - n[0], nodes[i + 1][1] - n[1])
    ]
    others = [(p[0] / 2, p[1] / 2) for p in blocked]
    return _straighten([(n[0] / 2, n[1] / 2) for n in corners], others)


class Step:
    """Drag one piece from one grid point to another.

    via_edges True always uses the gutters between squares, False always
    goes straight, and None goes straight unless another piece is in the
    way (which needs the occupied squares when the step runs).
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
        self._lattice = None

    def dragging_at(self, feed):
        """Drag pieces at feed until the returned function is called; head travel keeps its speed."""
        saved = self.drag_feed
        self.drag_feed = feed

        def restore():
            self.drag_feed = saved

        return restore

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

    def lattice(self):
        """The half-square points around the board that the machine can reach."""
        if self._lattice is None:
            points = set()
            for hx in LATTICE_SPAN:
                for hy in LATTICE_SPAN:
                    try:
                        self.machine.check_reach(*self.geometry.to_mm((hx / 2, hy / 2)))
                    except ValueError:
                        continue
                    points.add((hx, hy))
            self._lattice = points
        return self._lattice

    def path(self, step, occupied=None):
        if step.leaves_board:
            if occupied is not None:
                quiet = quiet_route(step.start, step.end, occupied, self.lattice())
                if quiet is not None:
                    return quiet
            if on_board(step.start):
                return route_out(step.start, step.end)
            return list(reversed(route_out(step.end, step.start)))
        via_edges = step.via_edges
        if via_edges is None:
            others = None if occupied is None else set(occupied) - {step.start}
            via_edges = others is None or not is_clear([step.start, step.end], others)
        return route(step.start, step.end, via_edges)

    def check(self, step):
        """Refuse a step before anything moves if any part of it is off the board or out of reach."""
        self._check(self.path(step), not step.leaves_board)

    def goto(self, point, occupied=None):
        """Move the head, magnet off, straight to a grid point.

        With the magnet off the head may pass under other pieces, so occupied
        is not used.
        """
        point = tuple(point)
        self._check([point], keep_on_board=False)
        x, y = self.geometry.to_mm(point)
        self.machine.move_to(x, y, self.travel_feed)

    def park(self, occupied=None):
        """Move the head, magnet off, to the machine's (0, 0) corner."""
        if self.machine.head is None:
            raise ValueError(
                "The head's position is unknown, so it can't be parked. Push it into its corner by hand."
            )
        self.machine.move_to(0, 0, self.travel_feed)
        self.machine.wait_until_idle()

    def run(self, step, occupied=None, settle=True):
        """Drag one piece. occupied (grid points of the other pieces) lets routes go straight when clear.

        With settle False the drag is only queued on the engraver; the caller
        waits for the machine to finish once all its drags are queued.
        """
        path = self.path(step, occupied)
        self._check(path, not step.leaves_board)
        self.goto(path[0], occupied)
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
        if settle:
            self.machine.wait_until_idle()
