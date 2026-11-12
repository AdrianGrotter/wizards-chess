import re

from .geometry import FILES, parse_square

GRID_HELP = """\
  A4 -> C2        drag the piece on A4 to C2 (also: A4 C2, A4-C2, a4 to c2)
  A4 -> C2 edges  same, travelling along the lines between squares
  A4              move the head under A4, magnet off
  grid            show the grid
  quit            leave"""

_MOVE = re.compile(
    r"^([a-h][1-8])\s*(?:->|-|\s+to\s+|\s+)\s*([a-h][1-8])(?:\s+(edges))?$"
)
_SQUARE = re.compile(r"^([a-h][1-8])$")


def parse_command(text):
    """Turn a typed line into ("move", start, end, via_edges), ("goto", square),
    ("grid",), ("help",) or ("quit",). Squares are returned in lower case."""
    text = text.strip().lower()
    if text in ("quit", "exit", "q"):
        return ("quit",)
    if text in ("grid", "show", ""):
        return ("grid",)
    if text in ("help", "?", "h"):
        return ("help",)
    match = _MOVE.match(text)
    if match:
        start, end, edges = match.groups()
        if start == end:
            raise ValueError("Start and end are the same square")
        return ("move", start, end, edges is not None)
    match = _SQUARE.match(text)
    if match:
        return ("goto", match.group(1))
    raise ValueError("Didn't understand %r. Type 'help'." % text)


def render(head=None, start=None, end=None):
    """The board as text, rank 8 on top.

    head, start and end are square names: @ marks the head, o where the last
    piece came from and * where it went.
    """
    marks = {}
    for square, mark in ((start, "o"), (end, "*"), (head, "@")):
        if square:
            marks[parse_square(square)] = mark
    header = "    " + "  ".join(f.upper() for f in FILES)
    lines = [header]
    for rank in range(7, -1, -1):
        cells = [marks.get((f, rank), ".") for f in range(8)]
        lines.append(" %d  %s   %d" % (rank + 1, "  ".join(cells), rank + 1))
    lines.append(header)
    lines.append("    @ head   o from   * to")
    return "\n".join(lines)
