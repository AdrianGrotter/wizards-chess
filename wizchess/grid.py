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

WORDS = {
    "quit": "quit", "exit": "quit", "q": "quit",
    "grid": "grid", "show": "grid",
    "help": "help", "?": "help", "h": "help",
    "reset": "reset", "clear": "clear",
    "put": "put", "remove": "remove", "del": "remove",
}
EXAMPLES = "Type a square (E4), a move (E2 -> E4), or 'help' for all commands."

_COMPACT_MOVE = re.compile(r"^([a-z]\d+)([a-z]\d+)([a-z])?$")


def square(token):
    """A typed square in lower case, or ValueError explaining what is wrong with it."""
    token = token.lower()
    if len(token) == 2 and token[0].isalpha() and token[1].isdigit():
        if token[0] not in FILES:
            raise ValueError("%s is not on the board: columns go from A to H." % token.upper())
        if token[1] not in "12345678":
            raise ValueError("%s is not on the board: rows go from 1 to 8." % token.upper())
        return token
    if len(token) >= 2 and token[0].isalpha() and token[1:].isdigit():
        raise ValueError("%s is not on the board: rows go from 1 to 8." % token.upper())
    raise ValueError(
        "'%s' is not a square. A square is a column A-H and a row 1-8, like E4." % token
    )


def _tokens(text):
    text = text.replace("->", " ").replace("=", " ")
    tokens = [t for t in re.split(r"\s+|-", text.strip()) if t and t.lower() != "to"]
    if tokens:
        match = _COMPACT_MOVE.match(tokens[0].lower())
        if match:
            tokens = [g for g in match.groups() if g] + tokens[1:]
    return tokens


def parse_command(text):
    """Turn a typed line into a command tuple, or ValueError with a message for the player.

    ("move", start, end, promotion or None), ("goto", sq), ("put", sq, piece),
    ("remove", sq), ("reset",), ("clear",), ("grid",), ("help",), ("quit",)
    Squares are returned in lower case; a put piece keeps its case (colour).
    """
    tokens = _tokens(text)
    if not tokens:
        return ("grid",)
    word = WORDS.get(tokens[0].lower())

    if word == "put":
        if len(tokens) != 3:
            raise ValueError("Use put with a square and a piece, like: put E4 N")
        piece = tokens[2]
        if len(piece) != 1 or piece.upper() not in "KQRBNP":
            raise ValueError(
                "'%s' is not a piece. Use K Q R B N P for white, k q r b n p for black." % piece
            )
        return ("put", square(tokens[1]), piece)
    if word == "remove":
        if len(tokens) != 2:
            raise ValueError("Use remove with one square, like: remove E4")
        return ("remove", square(tokens[1]))
    if word:
        if len(tokens) > 1:
            raise ValueError("'%s' doesn't take anything after it." % tokens[0])
        return (word,)

    if not (tokens[0][:1].isalpha() and tokens[0][1:].isdigit()):
        raise ValueError("Unknown command '%s'. %s" % (tokens[0], EXAMPLES))
    start = square(tokens[0])
    if len(tokens) == 1:
        return ("goto", start)
    end = square(tokens[1])
    if start == end:
        raise ValueError("%s -> %s starts and ends on the same square." % (start.upper(), end.upper()))
    promotion = None
    if len(tokens) >= 3:
        promotion = tokens[2].lower()
        if len(tokens) > 3 or promotion not in "qrbn" or len(promotion) != 1:
            raise ValueError(
                "Unexpected '%s' after the move. Only a promotion piece can follow: Q, R, B or N."
                % " ".join(tokens[2:])
            )
    return ("move", start, end, promotion)


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
