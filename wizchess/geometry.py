FILES = "abcdefgh"

# Grid coordinates of the board's outer edges: half a square beyond a1 and h8.
BOARD_EDGE_LOW = -0.5
BOARD_EDGE_HIGH = 7.5


def parse_square(name):
    name = name.strip().lower()
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError("Not a square: %r" % name)
    return (FILES.index(name[0]), int(name[1]) - 1)


def square_name(point):
    return FILES[int(point[0])] + str(int(point[1]) + 1)


def on_board(point):
    return all(BOARD_EDGE_LOW <= v <= BOARD_EDGE_HIGH for v in point)


class Geometry:
    """Converts board grid points to machine millimetres and back.

    A grid point is (file, rank) with a1 at (0, 0) and h8 at (7, 7).
    Fractional and out-of-range values address the lines between squares
    and the area around the board.

    The mapping comes from the measured centres of a1, h1 and a8, so a
    board that sits slightly rotated, or mirrored, is still hit dead centre.
    """

    def __init__(self, a1, h1, a8):
        self.origin = (float(a1[0]), float(a1[1]))
        self.file_step = ((h1[0] - a1[0]) / 7.0, (h1[1] - a1[1]) / 7.0)
        self.rank_step = ((a8[0] - a1[0]) / 7.0, (a8[1] - a1[1]) / 7.0)
        self._det = self.file_step[0] * self.rank_step[1] - self.rank_step[0] * self.file_step[1]
        if abs(self._det) < 1e-9:
            raise ValueError(
                "The calibration points a1, h1 and a8 lie on one line. Measure them again with jog."
            )

    @classmethod
    def from_config(cls, board):
        a1 = board["a1"]
        if "h1" in board and "a8" in board:
            return cls(a1, board["h1"], board["a8"])
        h8 = board["h8"]
        if board.get("files_along", "x") == "x":
            return cls(a1, (h8[0], a1[1]), (a1[0], h8[1]))
        return cls(a1, (a1[0], h8[1]), (h8[0], a1[1]))

    def to_mm(self, point):
        f, r = point
        return (
            self.origin[0] + f * self.file_step[0] + r * self.rank_step[0],
            self.origin[1] + f * self.file_step[1] + r * self.rank_step[1],
        )

    def to_grid(self, mm):
        dx, dy = mm[0] - self.origin[0], mm[1] - self.origin[1]
        f = (self.rank_step[1] * dx - self.rank_step[0] * dy) / self._det
        r = (self.file_step[0] * dy - self.file_step[1] * dx) / self._det
        return (f, r)

    def square_mm(self, name):
        return self.to_mm(parse_square(name))

    def square_at(self, mm, tolerance=0.05):
        """The square whose centre is at mm (within tolerance squares), or None."""
        f, r = self.to_grid(mm)
        rf, rr = round(f), round(r)
        if abs(f - rf) <= tolerance and abs(r - rr) <= tolerance and 0 <= rf <= 7 and 0 <= rr <= 7:
            return square_name((rf, rr))
        return None
