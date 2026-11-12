"""Chess rules small enough for MicroPython.

Offers the part of the python-chess interface that wizchess uses, with the
same names and behaviour, so the game code runs unchanged on the ESP32 where
python-chess itself does not fit. Squares are numbers 0 (a1) to 63 (h8).
"""

WHITE = True
BLACK = False

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6
PIECE_SYMBOLS = [None, "p", "n", "b", "r", "q", "k"]
PIECE_NAMES = [None, "pawn", "knight", "bishop", "rook", "queen", "king"]

FILE_NAMES = "abcdefgh"
RANK_NAMES = "12345678"
SQUARES = list(range(64))
SQUARE_NAMES = [f + r for r in RANK_NAMES for f in FILE_NAMES]
for _i, _name in enumerate(SQUARE_NAMES):
    globals()[_name.upper()] = _i

BB_A1, BB_H1, BB_A8, BB_H8 = 1 << 0, 1 << 7, 1 << 56, 1 << 63

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

STATUS_VALID = 0
STATUS_NO_WHITE_KING = 1 << 0
STATUS_NO_BLACK_KING = 1 << 1
STATUS_TOO_MANY_KINGS = 1 << 2
STATUS_TOO_MANY_WHITE_PAWNS = 1 << 3
STATUS_TOO_MANY_BLACK_PAWNS = 1 << 4
STATUS_PAWNS_ON_BACKRANK = 1 << 5
STATUS_TOO_MANY_WHITE_PIECES = 1 << 6
STATUS_TOO_MANY_BLACK_PIECES = 1 << 7
STATUS_BAD_CASTLING_RIGHTS = 1 << 8
STATUS_INVALID_EP_SQUARE = 1 << 9
STATUS_OPPOSITE_CHECK = 1 << 10
STATUS_EMPTY = 1 << 11
STATUS_TOO_MANY_CHECKERS = 1 << 16
STATUS_IMPOSSIBLE_CHECK = 1 << 17

_STRAIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
_KNIGHT_STEPS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))


def square(file_index, rank_index):
    return rank_index * 8 + file_index


def square_file(sq):
    return sq & 7


def square_rank(sq):
    return sq >> 3


def square_name(sq):
    return SQUARE_NAMES[sq]


def parse_square(name):
    if len(name) != 2 or name[0] not in FILE_NAMES or name[1] not in RANK_NAMES:
        raise ValueError("invalid square name: %r" % name)
    return FILE_NAMES.index(name[0]) + 8 * RANK_NAMES.index(name[1])


def square_distance(a, b):
    return max(abs((a & 7) - (b & 7)), abs((a >> 3) - (b >> 3)))


def piece_name(piece_type):
    return PIECE_NAMES[piece_type]


def _step(a, b):
    """The (file, rank) step from a toward b along a shared line, or None if they share none."""
    df, dr = (b & 7) - (a & 7), (b >> 3) - (a >> 3)
    if a == b or not (df == 0 or dr == 0 or abs(df) == abs(dr)):
        return None
    return ((df > 0) - (df < 0), (dr > 0) - (dr < 0))


def between(a, b):
    """The squares strictly between a and b when they share a rank, file or diagonal."""
    step = _step(a, b)
    if step is None:
        return []
    squares = []
    sq = a + step[0] + 8 * step[1]
    while sq != b:
        squares.append(sq)
        sq += step[0] + 8 * step[1]
    return squares


def SquareSet(squares):
    return list(squares)


def _targets(sq, steps):
    f, r = sq & 7, sq >> 3
    return [(r + dr) * 8 + f + df for df, dr in steps if 0 <= f + df < 8 and 0 <= r + dr < 8]


def _ray(sq, step):
    squares = []
    f, r = (sq & 7) + step[0], (sq >> 3) + step[1]
    while 0 <= f < 8 and 0 <= r < 8:
        squares.append(r * 8 + f)
        f += step[0]
        r += step[1]
    return squares


_KNIGHT = [_targets(sq, _KNIGHT_STEPS) for sq in SQUARES]
_KING = [_targets(sq, _STRAIGHT + _DIAGONAL) for sq in SQUARES]
# For each square, eight rays: four along ranks and files, then four diagonals.
_RAYS = [[_ray(sq, step) for step in _STRAIGHT + _DIAGONAL] for sq in SQUARES]


class Piece:
    def __init__(self, piece_type, color):
        self.piece_type = piece_type
        self.color = color

    def symbol(self):
        symbol = PIECE_SYMBOLS[self.piece_type]
        return symbol.upper() if self.color else symbol

    @classmethod
    def from_symbol(cls, symbol):
        if len(symbol) != 1 or symbol.lower() not in "pnbrqk":
            raise ValueError("invalid piece symbol: %r" % symbol)
        return cls(PIECE_SYMBOLS.index(symbol.lower()), symbol.isupper())

    def __eq__(self, other):
        return isinstance(other, Piece) and self.piece_type == other.piece_type and self.color == other.color

    def __hash__(self):
        return self.piece_type * 2 + (1 if self.color else 0)

    def __repr__(self):
        return "Piece.from_symbol(%r)" % self.symbol()


class Move:
    def __init__(self, from_square, to_square, promotion=None):
        self.from_square = from_square
        self.to_square = to_square
        self.promotion = promotion

    def uci(self):
        text = SQUARE_NAMES[self.from_square] + SQUARE_NAMES[self.to_square]
        return text + PIECE_SYMBOLS[self.promotion] if self.promotion else text

    @classmethod
    def from_uci(cls, uci):
        if len(uci) not in (4, 5):
            raise ValueError("expected a move like e2e4: %r" % uci)
        from_square, to_square = parse_square(uci[0:2]), parse_square(uci[2:4])
        promotion = None
        if len(uci) == 5:
            if uci[4] not in "nbrq":
                raise ValueError("invalid promotion piece: %r" % uci)
            promotion = PIECE_SYMBOLS.index(uci[4])
        if from_square == to_square:
            raise ValueError("a move can't start and end on the same square: %r" % uci)
        return cls(from_square, to_square, promotion)

    def __eq__(self, other):
        return (
            isinstance(other, Move)
            and self.from_square == other.from_square
            and self.to_square == other.to_square
            and self.promotion == other.promotion
        )

    def __hash__(self):
        return self.from_square | (self.to_square << 6) | ((self.promotion or 0) << 12)

    def __repr__(self):
        return "Move.from_uci(%r)" % self.uci()


class Board:
    def __init__(self, fen=STARTING_FEN):
        self.squares = [None] * 64
        self._stack = []
        self.set_fen(fen)

    def reset(self):
        self.set_fen(STARTING_FEN)

    def clear(self):
        self.set_fen("8/8/8/8/8/8/8/8 w - - 0 1")

    def clear_stack(self):
        self._stack = []

    def piece_at(self, sq):
        return self.squares[sq]

    def color_at(self, sq):
        piece = self.squares[sq]
        return None if piece is None else piece.color

    def piece_map(self):
        return {sq: piece for sq, piece in enumerate(self.squares) if piece is not None}

    def set_piece_at(self, sq, piece):
        self.squares[sq] = piece

    def remove_piece_at(self, sq):
        piece = self.squares[sq]
        self.squares[sq] = None
        return piece

    def king(self, color):
        for sq in range(63, -1, -1):
            piece = self.squares[sq]
            if piece is not None and piece.piece_type == KING and piece.color == color:
                return sq
        return None

    def _attackers(self, color, sq, squares=None):
        """Squares of the pieces of color that attack sq, on this board or on the given squares."""
        if squares is None:
            squares = self.squares
        found = []
        for s in _KNIGHT[sq]:
            p = squares[s]
            if p is not None and p.piece_type == KNIGHT and p.color == color:
                found.append(s)
        for s in _KING[sq]:
            p = squares[s]
            if p is not None and p.piece_type == KING and p.color == color:
                found.append(s)
        for i, ray in enumerate(_RAYS[sq]):
            slider = ROOK if i < 4 else BISHOP
            for s in ray:
                p = squares[s]
                if p is None:
                    continue
                if p.color == color and (p.piece_type == QUEEN or p.piece_type == slider):
                    found.append(s)
                break
        pawn_rank = (sq >> 3) + (-1 if color else 1)
        if 0 <= pawn_rank < 8:
            for pawn_file in ((sq & 7) - 1, (sq & 7) + 1):
                if 0 <= pawn_file < 8:
                    s = pawn_rank * 8 + pawn_file
                    p = squares[s]
                    if p is not None and p.piece_type == PAWN and p.color == color:
                        found.append(s)
        return found

    def is_attacked_by(self, color, sq):
        return bool(self._attackers(color, sq))

    def _checkers(self):
        king = self.king(self.turn)
        return [] if king is None else self._attackers(not self.turn, king)

    def is_check(self):
        return bool(self._checkers())

    def clean_castling_rights(self):
        """The castling rights that still have their king and rook on their starting squares."""
        rights = 0
        for color, king_square, corners in ((WHITE, 4, (BB_A1, BB_H1)), (BLACK, 60, (BB_A8, BB_H8))):
            if self.squares[king_square] != Piece(KING, color):
                continue
            for corner in corners:
                rook_square = _lowest_bit(corner)
                if self.castling_rights & corner and self.squares[rook_square] == Piece(ROOK, color):
                    rights |= corner
        return rights

    def has_kingside_castling_rights(self, color):
        return bool(self.clean_castling_rights() & (BB_H1 if color else BB_H8))

    def has_queenside_castling_rights(self, color):
        return bool(self.clean_castling_rights() & (BB_A1 if color else BB_A8))

    def _castling_moves(self):
        us = self.turn
        rank = 0 if us else 7
        king = rank * 8 + 4
        rights = self.clean_castling_rights()
        moves = []
        if not rights & ((BB_A1 | BB_H1) if us else (BB_A8 | BB_H8)):
            return moves
        if self._attackers(not us, king):
            return moves
        squares = self.squares
        if rights & (BB_H1 if us else BB_H8):
            if squares[king + 1] is None and squares[king + 2] is None and not (
                self._attackers(not us, king + 1) or self._attackers(not us, king + 2)
            ):
                moves.append(Move(king, king + 2))
        if rights & (BB_A1 if us else BB_A8):
            if squares[king - 1] is None and squares[king - 2] is None and squares[king - 3] is None and not (
                self._attackers(not us, king - 1) or self._attackers(not us, king - 2)
            ):
                moves.append(Move(king, king - 2))
        return moves

    def _pawn_moves(self, sq, moves):
        squares = self.squares
        us = self.turn
        forward = 8 if us else -8
        rank, file_index = sq >> 3, sq & 7
        last_rank = 6 if us else 1
        if not 0 <= sq + forward < 64:
            return

        def add(to):
            if rank == last_rank:
                for promotion in (QUEEN, ROOK, BISHOP, KNIGHT):
                    moves.append(Move(sq, to, promotion))
            else:
                moves.append(Move(sq, to))

        if squares[sq + forward] is None:
            add(sq + forward)
            if rank == (1 if us else 6) and squares[sq + 2 * forward] is None:
                moves.append(Move(sq, sq + 2 * forward))
        for side in (-1, 1):
            if not 0 <= file_index + side < 8:
                continue
            to = sq + forward + side
            target = squares[to]
            if target is not None:
                if target.color != us:
                    add(to)
            elif to == self.ep_square and rank == (4 if us else 3):
                moves.append(Move(sq, to))

    def _pseudo_legal_moves(self):
        squares = self.squares
        us = self.turn
        moves = []
        for sq in range(64):
            piece = squares[sq]
            if piece is None or piece.color != us:
                continue
            kind = piece.piece_type
            if kind == PAWN:
                self._pawn_moves(sq, moves)
            elif kind == KNIGHT or kind == KING:
                for to in (_KNIGHT if kind == KNIGHT else _KING)[sq]:
                    target = squares[to]
                    if target is None or target.color != us:
                        moves.append(Move(sq, to))
            else:
                rays = _RAYS[sq]
                if kind == ROOK:
                    rays = rays[:4]
                elif kind == BISHOP:
                    rays = rays[4:]
                for ray in rays:
                    for to in ray:
                        target = squares[to]
                        if target is None:
                            moves.append(Move(sq, to))
                            continue
                        if target.color != us:
                            moves.append(Move(sq, to))
                        break
        moves.extend(self._castling_moves())
        return moves

    def _keeps_king_safe(self, move):
        """Whether the side to move still has its king out of check after a pseudo-legal move.

        Tried on a copy: the board itself may be read from another thread and
        must never show a move that is only being considered.
        """
        squares = list(self.squares)
        us = self.turn
        if self.is_en_passant(move):
            squares[move.to_square + (-8 if us else 8)] = None
        squares[move.to_square] = squares[move.from_square]
        squares[move.from_square] = None
        king = None
        for sq in range(63, -1, -1):
            piece = squares[sq]
            if piece is not None and piece.piece_type == KING and piece.color == us:
                king = sq
                break
        return king is None or not self._attackers(not us, king, squares)

    @property
    def legal_moves(self):
        return [m for m in self._pseudo_legal_moves() if self._keeps_king_safe(m)]

    def is_pseudo_legal(self, move):
        return move in self._pseudo_legal_moves()

    def is_legal(self, move):
        return self.is_pseudo_legal(move) and self._keeps_king_safe(move)

    def is_en_passant(self, move):
        piece = self.squares[move.from_square]
        return (
            self.ep_square == move.to_square
            and piece is not None
            and piece.piece_type == PAWN
            and abs(move.to_square - move.from_square) in (7, 9)
            and self.squares[move.to_square] is None
        )

    def is_capture(self, move):
        target = self.squares[move.to_square]
        return (target is not None and target.color != self.turn) or self.is_en_passant(move)

    def is_castling(self, move):
        piece = self.squares[move.from_square]
        if piece is None or piece.piece_type != KING:
            return False
        target = self.squares[move.to_square]
        return abs((move.from_square & 7) - (move.to_square & 7)) > 1 or (
            target is not None and target.piece_type == ROOK and target.color == self.turn
        )

    def is_kingside_castling(self, move):
        return self.is_castling(move) and (move.to_square & 7) > (move.from_square & 7)

    def is_queenside_castling(self, move):
        return self.is_castling(move) and (move.to_square & 7) < (move.from_square & 7)

    def _position_key(self):
        placement = "".join("." if p is None else p.symbol() for p in self.squares)
        ep = self.ep_square if self._has_legal_en_passant() else None
        return (placement, self.turn, self.clean_castling_rights(), ep)

    def push(self, move):
        us = self.turn
        piece = self.squares[move.from_square]
        if piece is None:
            raise ValueError("no piece on %s" % SQUARE_NAMES[move.from_square])
        squares = list(self.squares)
        self._stack.append((
            self.squares, us, self.castling_rights, self.ep_square,
            self.halfmove_clock, self.fullmove_number, self._position_key(),
        ))
        capture = self.is_capture(move)
        en_passant = self.is_en_passant(move)
        castling = self.is_castling(move)

        self.ep_square = None
        self.halfmove_clock = 0 if (capture or piece.piece_type == PAWN) else self.halfmove_clock + 1
        if not us:
            self.fullmove_number += 1

        self.castling_rights &= ~((1 << move.from_square) | (1 << move.to_square))
        if piece.piece_type == KING:
            self.castling_rights &= ~((BB_A1 | BB_H1) if us else (BB_A8 | BB_H8))

        squares[move.from_square] = None
        if castling:
            rank = move.from_square & ~7
            kingside = (move.to_square & 7) > (move.from_square & 7)
            rook_from = rank + (7 if kingside else 0)
            squares[rook_from] = None
            squares[rank + (6 if kingside else 2)] = piece
            squares[rank + (5 if kingside else 3)] = Piece(ROOK, us)
        else:
            if en_passant:
                squares[move.to_square + (-8 if us else 8)] = None
            elif piece.piece_type == PAWN and abs(move.to_square - move.from_square) == 16:
                self.ep_square = move.from_square + (8 if us else -8)
            squares[move.to_square] = Piece(move.promotion, us) if move.promotion else piece
        self.squares = squares
        self.turn = not us

    def pop(self):
        (self.squares, self.turn, self.castling_rights, self.ep_square,
         self.halfmove_clock, self.fullmove_number, _) = self._stack.pop()

    def push_uci(self, uci):
        move = Move.from_uci(uci)
        if move not in self.legal_moves:
            raise ValueError("illegal move: %r" % uci)
        self.push(move)
        return move

    def push_san(self, san):
        move = self.parse_san(san)
        self.push(move)
        return move

    def parse_san(self, san):
        """The legal move written as e4, Nf3, exd5, Nbd2, e8=Q or O-O; ValueError otherwise."""
        legal = self.legal_moves
        text = san.rstrip("+#")
        if text in ("O-O", "0-0", "O-O-O", "0-0-0"):
            kingside = len(text) == 3
            for move in legal:
                if self.is_castling(move) and self.is_kingside_castling(move) == kingside:
                    return move
            raise ValueError("illegal san: %r" % san)

        promotion = None
        if len(text) > 2 and text[-1] in "nbrqNBRQ" and text[-2] in "=12345678":
            promotion = PIECE_SYMBOLS.index(text[-1].lower())
            text = text[:-1].rstrip("=")
        if len(text) < 2:
            raise ValueError("invalid san: %r" % san)
        try:
            to_square = parse_square(text[-2:])
        except ValueError:
            raise ValueError("invalid san: %r" % san)
        text = text[:-2]
        kind = PAWN
        if text and text[0] in "NBRQK":
            kind = PIECE_SYMBOLS.index(text[0].lower())
            text = text[1:]
        if text and text[-1] in "x-":
            text = text[:-1]
        from_file = from_rank = None
        for char in text:
            if char in FILE_NAMES and from_file is None and from_rank is None:
                from_file = FILE_NAMES.index(char)
            elif char in RANK_NAMES and from_rank is None:
                from_rank = RANK_NAMES.index(char)
            else:
                raise ValueError("invalid san: %r" % san)
        if kind == PAWN and from_file is None:
            from_file = to_square & 7

        found = None
        for move in legal:
            if move.to_square != to_square or move.promotion != promotion:
                continue
            if self.squares[move.from_square].piece_type != kind:
                continue
            if from_file is not None and (move.from_square & 7) != from_file:
                continue
            if from_rank is not None and (move.from_square >> 3) != from_rank:
                continue
            if found is not None:
                raise ValueError("ambiguous san: %r" % san)
            found = move
        if found is None:
            raise ValueError("illegal san: %r" % san)
        return found

    def is_checkmate(self):
        return self.is_check() and not self.legal_moves

    def is_stalemate(self):
        return not self.is_check() and not self.legal_moves

    def _has_insufficient_material(self, color):
        own = [p.piece_type for p in self.squares if p is not None and p.color == color]
        if PAWN in own or ROOK in own or QUEEN in own:
            return False
        if KNIGHT in own:
            others = [p.piece_type for p in self.squares if p is not None and p.color != color]
            return len(own) <= 2 and all(kind in (KING, QUEEN) for kind in others)
        if BISHOP in own:
            shades = set()
            for sq, p in enumerate(self.squares):
                if p is None:
                    continue
                if p.piece_type in (PAWN, KNIGHT):
                    return False
                if p.piece_type == BISHOP:
                    shades.add(((sq & 7) + (sq >> 3)) & 1)
            return len(shades) < 2
        return True

    def is_insufficient_material(self):
        return self._has_insufficient_material(WHITE) and self._has_insufficient_material(BLACK)

    def is_seventyfive_moves(self):
        return self.halfmove_clock >= 150 and bool(self.legal_moves)

    def is_fivefold_repetition(self):
        key = self._position_key()
        return 1 + sum(1 for state in self._stack if state[6] == key) >= 5

    def is_game_over(self):
        return self.result() != "*"

    def result(self):
        if not self.legal_moves:
            if not self.is_check():
                return "1/2-1/2"
            return "0-1" if self.turn else "1-0"
        if self.is_insufficient_material() or self.halfmove_clock >= 150 or self.is_fivefold_repetition():
            return "1/2-1/2"
        return "*"

    def _valid_ep_square(self):
        ep = self.ep_square
        if ep is None:
            return None
        us = self.turn
        if (ep >> 3) != (5 if us else 2):
            return None
        pushed_to = ep + (-8 if us else 8)
        pushed_from = ep + (8 if us else -8)
        if self.squares[pushed_to] != Piece(PAWN, not us):
            return None
        if self.squares[ep] is not None or self.squares[pushed_from] is not None:
            return None
        return ep

    def _has_legal_en_passant(self):
        ep = self.ep_square
        if ep is None:
            return False
        moves = []
        for side in (-1, 1):
            sq = ep + (-8 if self.turn else 8) + side
            if 0 <= (ep & 7) + side < 8 and self.squares[sq] == Piece(PAWN, self.turn):
                self._pawn_moves(sq, moves)
        return any(m.to_square == ep and self._keeps_king_safe(m) for m in moves)

    def status(self):
        """Flags for everything that stops this from being a position a real game can reach."""
        errors = STATUS_VALID
        pieces = [p for p in self.squares if p is not None]
        if not pieces:
            errors |= STATUS_EMPTY
        count = {}
        for p in pieces:
            count[p] = count.get(p, 0) + 1
        if not count.get(Piece(KING, WHITE)):
            errors |= STATUS_NO_WHITE_KING
        if not count.get(Piece(KING, BLACK)):
            errors |= STATUS_NO_BLACK_KING
        if count.get(Piece(KING, WHITE), 0) + count.get(Piece(KING, BLACK), 0) > 2:
            errors |= STATUS_TOO_MANY_KINGS
        if sum(1 for p in pieces if p.color) > 16:
            errors |= STATUS_TOO_MANY_WHITE_PIECES
        if sum(1 for p in pieces if not p.color) > 16:
            errors |= STATUS_TOO_MANY_BLACK_PIECES
        if count.get(Piece(PAWN, WHITE), 0) > 8:
            errors |= STATUS_TOO_MANY_WHITE_PAWNS
        if count.get(Piece(PAWN, BLACK), 0) > 8:
            errors |= STATUS_TOO_MANY_BLACK_PAWNS
        for sq in list(range(8)) + list(range(56, 64)):
            p = self.squares[sq]
            if p is not None and p.piece_type == PAWN:
                errors |= STATUS_PAWNS_ON_BACKRANK
                break
        if self.castling_rights != self.clean_castling_rights():
            errors |= STATUS_BAD_CASTLING_RIGHTS
        valid_ep = self._valid_ep_square()
        if self.ep_square != valid_ep:
            errors |= STATUS_INVALID_EP_SQUARE

        their_king = self.king(not self.turn)
        if their_king is not None and self._attackers(self.turn, their_king):
            errors |= STATUS_OPPOSITE_CHECK

        checkers = self._checkers()
        if checkers:
            king = self.king(self.turn)
            if len(checkers) > 2:
                errors |= STATUS_TOO_MANY_CHECKERS
            if valid_ep is not None:
                pushed_to = valid_ep + (-8 if self.turn else 8)
                pushed_from = valid_ep + (8 if self.turn else -8)
                before = list(self.squares)
                before[pushed_to], before[pushed_from] = None, before[pushed_to]
                checked_before = bool(self._attackers(not self.turn, king, before))
                if len(checkers) > 1 or (max(checkers) != pushed_to and checked_before):
                    errors |= STATUS_IMPOSSIBLE_CHECK
            elif len(checkers) > 2 or (len(checkers) == 2 and _on_one_line(min(checkers), max(checkers), king)):
                errors |= STATUS_IMPOSSIBLE_CHECK
        return errors

    def board_fen(self):
        rows = []
        for rank in range(7, -1, -1):
            row, empty = "", 0
            for file_index in range(8):
                piece = self.squares[rank * 8 + file_index]
                if piece is None:
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece.symbol()
            rows.append(row + (str(empty) if empty else ""))
        return "/".join(rows)

    def fen(self):
        rights = self.clean_castling_rights()
        castling = "".join(
            letter for letter, corner in (("K", BB_H1), ("Q", BB_A1), ("k", BB_H8), ("q", BB_A8)) if rights & corner
        )
        ep = SQUARE_NAMES[self.ep_square] if self._has_legal_en_passant() else "-"
        return "%s %s %s %s %d %d" % (
            self.board_fen(), "w" if self.turn else "b", castling or "-", ep,
            self.halfmove_clock, self.fullmove_number,
        )

    def set_fen(self, fen):
        parts = fen.split()
        if not parts:
            raise ValueError("empty fen")
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError("expected 8 rows in the position part of the fen: %r" % fen)
        squares = [None] * 64
        for i, row in enumerate(rows):
            rank, file_index = 7 - i, 0
            for char in row:
                if char in "12345678":
                    file_index += int(char)
                else:
                    if file_index > 7:
                        raise ValueError("a row of the fen is too long: %r" % fen)
                    squares[rank * 8 + file_index] = Piece.from_symbol(char)
                    file_index += 1
            if file_index != 8:
                raise ValueError("a row of the fen does not have 8 squares: %r" % fen)
        turn = parts[1] if len(parts) > 1 else "w"
        if turn not in ("w", "b"):
            raise ValueError("expected w or b for the turn in the fen: %r" % fen)
        castling = parts[2] if len(parts) > 2 else "-"
        rights = 0
        for char in castling:
            if char == "-":
                continue
            if char not in "KQkq":
                raise ValueError("invalid castling part in the fen: %r" % fen)
            rights |= {"K": BB_H1, "Q": BB_A1, "k": BB_H8, "q": BB_A8}[char]
        ep = parts[3] if len(parts) > 3 else "-"
        self.squares = squares
        self.turn = turn == "w"
        self.castling_rights = rights
        self.ep_square = None if ep == "-" else parse_square(ep)
        self.halfmove_clock = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove_number = int(parts[5]) if len(parts) > 5 else 1
        self._stack = []

    def __str__(self):
        return "\n".join(
            " ".join("." if p is None else p.symbol() for p in self.squares[rank * 8:rank * 8 + 8])
            for rank in range(7, -1, -1)
        )


def _lowest_bit(mask):
    index = 0
    while not mask & 1:
        mask >>= 1
        index += 1
    return index


def _on_one_line(a, b, c):
    """Whether three distinct squares share one rank, file or diagonal."""
    step = _step(a, b)
    return step is not None and _step(a, c) in (step, (-step[0], -step[1]))
