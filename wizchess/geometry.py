FILES = "abcdefgh"


def parse_square(name):
    name = name.strip().lower()
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError("Not a square: %r" % name)
    return (FILES.index(name[0]), int(name[1]) - 1)


class Geometry:
    """Converts board grid points to machine millimetres.

    A grid point is (file, rank) with a1 at (0, 0) and h8 at (7, 7).
    Fractional and out-of-range values address the lines between squares
    and the area around the board.
    """

    def __init__(self, a1, h8, files_along="x"):
        if files_along not in ("x", "y"):
            raise ValueError("files_along must be 'x' or 'y'")
        self.a1 = (float(a1[0]), float(a1[1]))
        self.h8 = (float(h8[0]), float(h8[1]))
        self.files_along = files_along

    @classmethod
    def from_config(cls, board):
        return cls(board["a1"], board["h8"], board.get("files_along", "x"))

    def to_mm(self, point):
        f, r = point
        step_x = (self.h8[0] - self.a1[0]) / 7
        step_y = (self.h8[1] - self.a1[1]) / 7
        if self.files_along == "x":
            return (self.a1[0] + f * step_x, self.a1[1] + r * step_y)
        return (self.a1[0] + r * step_x, self.a1[1] + f * step_y)

    def square_mm(self, name):
        return self.to_mm(parse_square(name))
