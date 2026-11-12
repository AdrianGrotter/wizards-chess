import chess


class ResetPlan:
    """How to get from a position back to the starting position.

    extra:   squares whose pieces have no place in the starting position
             (for example a second queen from a promotion) and must be lifted off.
    moves:   (from_square, to_square) drags in an order where every target is
             empty when its piece arrives.
    missing: (square, piece) pairs that are not on the board at all, such as
             captured pieces, and must be put back by hand.
    """

    def __init__(self, extra, moves, missing):
        self.extra = extra
        self.moves = moves
        self.missing = missing


def _distance(a, b):
    df = chess.square_file(a) - chess.square_file(b)
    dr = chess.square_rank(a) - chess.square_rank(b)
    return df * df + dr * dr


def _match(sources, targets):
    """Pair sources with targets, nearest pairs first. Returns (pairs, unmatched sources, unmatched targets)."""
    sources, targets = sorted(sources), sorted(targets)
    pairs = []
    while sources and targets:
        s, t = min(((s, t) for s in sources for t in targets), key=lambda p: (_distance(*p), p))
        pairs.append((s, t))
        sources.remove(s)
        targets.remove(t)
    return pairs, sources, targets


def _buffer_square(occupied, reserved, near):
    """An empty square, off the start ranks if possible, near the piece that must step aside."""
    free = [sq for sq in chess.SQUARES if sq not in occupied and sq not in reserved]
    middle = [sq for sq in free if 2 <= chess.square_rank(sq) <= 5]
    return min(middle or free, key=lambda sq: (_distance(sq, near), sq))


def _order(moves, occupied):
    """Order drags so each lands on an empty square, stepping a piece aside to break cycles."""
    moves = dict(moves)
    occupied = set(occupied)
    ordered = []
    while moves:
        ready = [s for s, t in moves.items() if t not in occupied]
        if ready:
            s = min(ready, key=lambda s: (_distance(s, moves[s]), s))
            t = moves.pop(s)
            ordered.append((s, t))
        else:
            s = min(moves)
            t = _buffer_square(occupied, set(moves.values()), s)
            moves[t] = moves.pop(s)
            ordered.append((s, t))
        occupied.discard(s)
        occupied.add(t)
    return ordered


def plan_reset(board):
    start = chess.Board().piece_map()
    current = board.piece_map()
    extra, missing, moves = [], [], {}
    kinds = set(start.values()) | set(current.values())
    for piece in sorted(kinds, key=lambda p: p.symbol()):
        targets = {sq for sq, p in start.items() if p == piece}
        sources = {sq for sq, p in current.items() if p == piece}
        staying = targets & sources
        pairs, left_sources, left_targets = _match(sources - staying, targets - staying)
        moves.update(pairs)
        extra.extend(left_sources)
        missing.extend((sq, piece) for sq in left_targets)
    occupied = set(current) - set(extra)
    return ResetPlan(sorted(extra), _order(moves, occupied), sorted(missing, key=lambda m: m[0]))
