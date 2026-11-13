import re

from .geometry import FILES

GRID_HELP = """\
  A4 C2           move the piece on A4 to C2 (also: A4C2, A4-C2, A4 -> C2)
  E7 E8 N         promote to a knight instead of a queen
  B1 C3 slow      drag the piece slowly (the head still travels to it at full speed)
  A4              move the head under A4, magnet off
  put E4 N        place a piece on the grid (white: KQRBNP, black: kqrbnp)
  remove E4       take a piece off the grid
  rules off       drag from any square to any square (A1 A8), nothing checked
  rules on        back to moves that follow the rules
  turn black      set whose turn it is (after fixing the grid by hand)
  reset           new game: drag every piece back to its starting square
  reset grid      new game on the grid only, after setting the pieces up by hand
  clear           empty grid (head stays where it is)
  park            head back to its corner, magnet off
  centre 4        end every drag with a spiral, 4 mm wide at first, that pulls the piece onto its square
  unlock          clear an engraver alarm
  grid            show the grid
  quit            send the head back to its corner and leave
Moves follow the chess rules and alternate between White and Black, unless rules are off.
Pieces: upper case white, lower case black. [ ] is the head, o where the last piece came from."""

WORDS = {
    "quit": "quit", "exit": "quit", "q": "quit",
    "grid": "grid", "show": "grid",
    "help": "help", "?": "help", "h": "help",
    "reset": "reset", "clear": "clear", "park": "park", "unlock": "unlock",
    "put": "put", "remove": "remove", "del": "remove", "turn": "turn", "rules": "rules",
    "centre": "centre", "center": "centre",
}
WIDEST_CENTRING_MM = 10
EXAMPLES = "Type a square (E4), a move (E2 E4), or 'help' for all commands."

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
    tokens = [t for t in text.replace("-", " ").split() if t.lower() != "to"]
    if tokens:
        match = _COMPACT_MOVE.match(tokens[0].lower())
        if match:
            tokens = [g for g in (match.group(1), match.group(2), match.group(3)) if g] + tokens[1:]
    return tokens


def parse_command(text):
    """Turn a typed line into a command tuple, or ValueError with a message for the player.

    ("move", start, end, promotion or None, slow), ("goto", sq, slow), ("put", sq, piece),
    ("remove", sq), ("turn", "white"|"black"), ("rules", "on"|"off"), ("reset", "pieces"|"grid"), ("clear",), ("park",),
    ("unlock",), ("centre", mm or None), ("grid",), ("help",), ("quit",)
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
    if word == "reset":
        if len(tokens) == 1:
            return ("reset", "pieces")
        if len(tokens) == 2 and tokens[1].lower() == "grid":
            return ("reset", "grid")
        raise ValueError("Use reset on its own, or reset grid to only reset the grid.")
    if word == "rules":
        if len(tokens) != 2 or tokens[1].lower() not in ("on", "off"):
            raise ValueError("Use rules with on or off, like: rules off")
        return ("rules", tokens[1].lower())
    if word == "turn":
        if len(tokens) != 2 or tokens[1].lower() not in ("white", "black"):
            raise ValueError("Use turn with white or black, like: turn black")
        return ("turn", tokens[1].lower())
    if word == "centre":
        if len(tokens) == 1:
            return ("centre", None)
        try:
            mm = float(tokens[1].replace(",", "."))
        except ValueError:
            mm = -1
        if len(tokens) != 2 or not 0 <= mm <= WIDEST_CENTRING_MM:
            raise ValueError(
                "Use centre with a distance from 0 to %d mm, like: centre 4 (0 switches it off)"
                % WIDEST_CENTRING_MM
            )
        return ("centre", mm)
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
    rest = tokens[1:]
    slow = any(t.lower() == "slow" for t in rest)
    rest = [t for t in rest if t.lower() != "slow"]
    if not rest:
        if slow:
            raise ValueError("'slow' only slows down dragging a piece, like: B1 C3 slow")
        return ("goto", start, False)
    end = square(rest[0])
    if start == end:
        raise ValueError("%s %s starts and ends on the same square." % (start.upper(), end.upper()))
    promotion = None
    if len(rest) >= 2:
        promotion = rest[1].lower()
        if len(rest) > 2 or promotion not in "qrbn" or len(promotion) != 1:
            raise ValueError(
                "Unexpected '%s' after the move. Only 'slow' or a promotion piece "
                "(Q, R, B or N) can follow." % " ".join(rest[1:])
            )
    return ("move", start, end, promotion, slow)


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
