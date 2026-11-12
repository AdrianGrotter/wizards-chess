import re

from .geometry import FILES, parse_square

GRID_HELP = """\
  A4 -> C2        drag the piece on A4 to C2 (also: A4 C2, A4-C2, a4 to c2)
  A4 -> C2 edges  same, forced along the lines between squares
  A4              move the head under A4, magnet off
  put E4 N        place a piece on the grid (white: KQRBNP, black: kqrbnp)
  remove E4       take a piece off the grid
  reset / clear   starting position / empty grid
  grid            show the grid
  quit            leave
Pieces: upper case white, lower case black. [ ] is the head, o where the last piece came from."""

PIECE_LETTERS = "KQRBNPkqrbnp"
BACK_RANK = "rnbqkbnr"

_MOVE = re.compile(r"^([a-h][1-8])\s*(?:->|-|\s+to\s+|\s+)\s*([a-h][1-8])(?:\s+(edges))?$")
_SQUARE = re.compile(r"^([a-h][1-8])$")
_PUT = re.compile(r"^put\s+([a-h][1-8])\s+([kqrbnp])$", re.IGNORECASE)
_REMOVE = re.compile(r"^(?:remove|del)\s+([a-h][1-8])$")


def starting_position():
    """Pieces by square name, upper case white, lower case black."""
    pieces = {}
    for i, f in enumerate(FILES):
        pieces[f + "1"] = BACK_RANK[i].upper()
        pieces[f + "2"] = "P"
        pieces[f + "7"] = "p"
        pieces[f + "8"] = BACK_RANK[i]
    return pieces


def parse_command(text):
    """Turn a typed line into a command tuple. Squares are returned in lower case.

    ("move", start, end, force_edges), ("goto", sq), ("put", sq, piece),
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
        start, end, edges = match.groups()
        if start == end:
            raise ValueError("Start and end are the same square")
        return ("move", start, end, edges is not None)
    match = _SQUARE.match(text)
    if match:
        return ("goto", match.group(1))
    raise ValueError("Didn't understand %r. Type 'help'." % stripped)


def needs_edges(pieces, start, end):
    """Whether a piece must travel along the lines between squares.

    A straight or diagonal path over empty squares can be dragged directly;
    knights, crooked paths and paths over other pieces go along the lines.
    """
    if pieces.get(start, "").lower() == "n":
        return True
    (f0, r0), (f1, r1) = parse_square(start), parse_square(end)
    df, dr = f1 - f0, r1 - r0
    if not (df == 0 or dr == 0 or abs(df) == abs(dr)):
        return True
    steps = max(abs(df), abs(dr))
    sf, sr = (df > 0) - (df < 0), (dr > 0) - (dr < 0)
    for i in range(1, steps):
        if FILES[f0 + i * sf] + str(r0 + i * sr + 1) in pieces:
            return True
    return False


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
