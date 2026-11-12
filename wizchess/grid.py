import re

from .geometry import FILES

GRID_HELP = """\
  A4 -> C2        move the piece on A4 to C2 (also: A4 C2, A4-C2, a4 to c2)
  E7 -> E8 N      promote to a knight instead of a queen
  A4              move the head under A4, magnet off
  put E4 N        place a piece on the grid (white: KQRBNP, black: kqrbnp)
  remove E4       take a piece off the grid
  reset / clear   starting position / empty grid
  grid            show the grid
  quit            leave
Moves follow the chess rules and alternate between White and Black.
Pieces: upper case white, lower case black. [ ] is the head, o where the last piece came from."""

_MOVE = re.compile(r"^([a-h][1-8])\s*(?:->|-|\s+to\s+|\s*)\s*([a-h][1-8])(?:\s*=?\s*([qrbn]))?$")
_SQUARE = re.compile(r"^([a-h][1-8])$")
_PUT = re.compile(r"^put\s+([a-h][1-8])\s+([kqrbnp])$", re.IGNORECASE)
_REMOVE = re.compile(r"^(?:remove|del)\s+([a-h][1-8])$")


def parse_command(text):
    """Turn a typed line into a command tuple. Squares are returned in lower case.

    ("move", start, end, promotion or None), ("goto", sq), ("put", sq, piece),
    ("remove", sq), ("reset",), ("clear",), ("grid",), ("help",), ("quit",)
    """
    stripped = text.strip()
    match = _PUT.match(stripped)
    if match:
        square, piece = match.groups()
        return ("put", square.lower(), piece)
    text = stripped.lower()
    if text in ("quit", "exit", "q"):
        return ("quit",)
    if text in ("grid", "show", ""):
        return ("grid",)
    if text in ("help", "?", "h"):
        return ("help",)
    if text in ("reset", "clear"):
        return (text,)
    match = _REMOVE.match(text)
    if match:
        return ("remove", match.group(1))
    match = _MOVE.match(text)
    if match:
        start, end, promotion = match.groups()
        if start == end:
            raise ValueError("Start and end are the same square")
        return ("move", start, end, promotion)
    match = _SQUARE.match(text)
    if match:
        return ("goto", match.group(1))
    raise ValueError("Didn't understand %r. Type 'help'." % stripped)


def render(pieces=None, head=None, came_from=None):
    """The grid as text, rank 8 on top."""
    pieces = pieces or {}
    header = "     " + "   ".join(f.upper() for f in FILES)
    lines = [header]
    for rank in range(8, 0, -1):
        cells = []
        for f in FILES:
            square = f + str(rank)
            mark = pieces.get(square) or ("o" if square == came_from else ".")
            cells.append("[%s]" % mark if square == head else " %s " % mark)
        lines.append(" %d  %s  %d" % (rank, " ".join(cells), rank))
    lines.append(header)
    return "\n".join(lines)
