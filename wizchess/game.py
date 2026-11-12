import chess

from .geometry import on_board, square_name
from .machine import MachineError
from .mover import Step

POSITION_PROBLEMS = [
    (chess.STATUS_EMPTY, "the grid is empty"),
    (chess.STATUS_NO_WHITE_KING, "White has no king"),
    (chess.STATUS_NO_BLACK_KING, "Black has no king"),
    (chess.STATUS_TOO_MANY_KINGS, "a side has more than one king"),
    (chess.STATUS_TOO_MANY_WHITE_PAWNS, "White has more than 8 pawns"),
    (chess.STATUS_TOO_MANY_BLACK_PAWNS, "Black has more than 8 pawns"),
    (chess.STATUS_TOO_MANY_WHITE_PIECES, "White has more than 16 pieces"),
    (chess.STATUS_TOO_MANY_BLACK_PIECES, "Black has more than 16 pieces"),
    (chess.STATUS_PAWNS_ON_BACKRANK, "a pawn stands on the first or last row"),
    (chess.STATUS_OPPOSITE_CHECK, "the side that is not moving is in check"),
    (chess.STATUS_TOO_MANY_CHECKERS, "the king is in check from too many pieces"),
    (chess.STATUS_IMPOSSIBLE_CHECK, "the king is in a check that can't happen in a real game"),
]


class MoveInterrupted(MachineError):
    """A move stopped after the engraver had started it, so the real board may differ from the grid."""


def grid(square):
    return (chess.square_file(square), chess.square_rank(square))


def place(point):
    if on_board(point) and float(point[0]).is_integer() and float(point[1]).is_integer():
        return square_name(point).upper()
    return "beside the board"


def position_problems(board):
    status = board.status()
    problems = [message for flag, message in POSITION_PROBLEMS if status & flag]
    if status and not problems:
        problems.append("this isn't a position a real game can reach")
    return problems


class Graveyard:
    """Hands out off-board grid points for captured pieces.

    columns maps "white"/"black" to the file columns their captured
    pieces are lined up in, eight per column from rank 1 upwards.
    """

    def __init__(self, columns):
        self.columns = columns
        self.count = {"white": 0, "black": 0}

    def peek_slot(self, color):
        index = self.count[color]
        columns = self.columns[color]
        if index >= 8 * len(columns):
            raise ValueError("No room left beside the board for captured %s pieces." % color)
        return (columns[index // 8], index % 8)

    def next_slot(self, color):
        slot = self.peek_slot(color)
        self.count[color] += 1
        return slot


def captured_square(board, move):
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
    return move.to_square


def _color_name(color):
    return "white" if color == chess.WHITE else "black"


def physical_steps(board, move, graveyard):
    """The piece drags needed to carry out a legal move on the given board.

    Without a graveyard, captured pieces are left for a player to remove.
    The graveyard slot is only looked at here; the caller takes it once the
    move has really happened.
    """
    steps = []
    captured = captured_square(board, move)
    if captured is not None and graveyard is not None:
        slot = graveyard.peek_slot(_color_name(board.color_at(captured)))
        steps.append(Step(grid(captured), slot, via_edges=True, leaves_board=True))

    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)
        if board.is_kingside_castling(move):
            rook_from, rook_to = (7, rank), (5, rank)
        else:
            rook_from, rook_to = (0, rank), (3, rank)
        steps.append(Step(grid(move.from_square), grid(move.to_square)))
        steps.append(Step(rook_from, rook_to, via_edges=True))
    else:
        is_knight = board.piece_type_at(move.from_square) == chess.KNIGHT
        steps.append(Step(grid(move.from_square), grid(move.to_square), via_edges=is_knight))
    return steps


class Game:
    def __init__(self, mover, graveyard=None, remove_by_hand=None):
        """remove_by_hand(square_name) is called before a capture when there is no graveyard.

        It returns False to call the move off; nothing has moved at that point.
        """
        self.board = chess.Board()
        self.mover = mover
        self.graveyard = graveyard
        self.remove_by_hand = remove_by_hand

    def reset(self):
        self.board.reset()

    def clear(self):
        self.board.clear()

    def put(self, square, symbol):
        self.board.set_piece_at(chess.parse_square(square), chess.Piece.from_symbol(symbol))
        self._tidy()

    def remove(self, square):
        self.board.remove_piece_at(chess.parse_square(square))
        self._tidy()

    def set_turn(self, color):
        self.board.turn = color == "white"
        self._tidy()

    def _tidy(self):
        """Drop castling and en passant rights that hand edits have made impossible."""
        self.board.castling_rights = self.board.clean_castling_rights()
        self.board.ep_square = None
        self.board.clear_stack()

    def problems(self):
        return position_problems(self.board)

    def parse(self, text):
        text = text.strip()
        try:
            move = chess.Move.from_uci(text.lower())
            if move in self.board.legal_moves:
                return move
        except ValueError:
            pass
        try:
            return self.board.parse_san(text)
        except ValueError:
            raise ValueError("Not a legal move here: %r" % text)

    def move_between(self, start, end, promotion=None):
        """The legal move from square start to square end, or ValueError saying why not.

        A pawn reaching the last rank becomes a queen unless promotion names
        another piece ("q", "r", "b" or "n").
        """
        problems = self.problems()
        if problems:
            raise ValueError(
                "Moves can't be checked until the grid is a real chess position: %s. "
                "Use put, remove or reset to fix it." % "; ".join(problems)
            )
        from_square, to_square = chess.parse_square(start), chess.parse_square(end)
        piece = self.board.piece_at(from_square)
        side = "White" if self.board.turn == chess.WHITE else "Black"
        if piece is None:
            raise ValueError("There is no piece on %s." % start.upper())
        if piece.color != self.board.turn:
            raise ValueError("It's %s's turn." % side)
        target = self.board.piece_at(to_square)
        if target is not None and target.color == piece.color:
            raise ValueError(
                "%s is occupied by your own %s." % (end.upper(), chess.piece_name(target.piece_type))
            )
        promotion_type = None
        if piece.piece_type == chess.PAWN and chess.square_rank(to_square) in (0, 7):
            promotion_type = chess.Piece.from_symbol(promotion or "q").piece_type
        elif promotion:
            raise ValueError("Only a pawn reaching the last rank can be promoted.")
        move = chess.Move(from_square, to_square, promotion=promotion_type)
        if move in self.board.legal_moves:
            return move
        if self.board.is_pseudo_legal(move):
            if self.board.is_castling(move):
                raise ValueError("%s can't castle out of, through or into check." % side)
            raise ValueError("That would leave the %s king in check." % side.lower())
        reason = self._blocked_reason(piece, from_square, to_square)
        if reason:
            raise ValueError(reason)
        if self._looks_like_castling(piece, from_square, to_square):
            raise ValueError(
                "%s can no longer castle on that side: the king or that rook has already moved."
                % side
            )
        raise ValueError(
            "A %s can't move from %s to %s."
            % (chess.piece_name(piece.piece_type), start.upper(), end.upper())
        )

    def _looks_like_castling(self, piece, from_square, to_square):
        home = chess.E1 if piece.color == chess.WHITE else chess.E8
        return (
            piece.piece_type == chess.KING
            and from_square == home
            and chess.square_rank(to_square) == chess.square_rank(home)
            and abs(chess.square_file(to_square) - chess.square_file(home)) == 2
        )

    def _owner(self, piece, mover):
        if piece.color == mover.color:
            return "your"
        return "White's" if piece.color == chess.WHITE else "Black's"

    def _blocked_reason(self, piece, from_square, to_square):
        """Why a move the piece could otherwise make is stopped by another piece, if it is."""
        df = chess.square_file(to_square) - chess.square_file(from_square)
        dr = chess.square_rank(to_square) - chess.square_rank(from_square)
        straight = df == 0 or dr == 0
        diagonal = abs(df) == abs(dr)
        forward = 1 if piece.color == chess.WHITE else -1
        start_rank = 1 if piece.color == chess.WHITE else 6
        kind = piece.piece_type
        follows_pattern = (
            (kind == chess.ROOK and straight)
            or (kind == chess.BISHOP and diagonal)
            or (kind == chess.QUEEN and (straight or diagonal))
            or (kind == chess.PAWN and df == 0 and (dr == forward or (
                dr == 2 * forward and chess.square_rank(from_square) == start_rank)))
            or (kind == chess.KING and dr == 0 and abs(df) == 2)
        )
        if not follows_pattern:
            return None
        between = sorted(
            chess.SquareSet(chess.between(from_square, to_square)),
            key=lambda sq: chess.square_distance(sq, from_square),
        )
        name = chess.piece_name(kind)
        for square in between:
            blocker = self.board.piece_at(square)
            if blocker:
                return "The %s on %s is blocked by %s %s on %s." % (
                    name,
                    chess.square_name(from_square).upper(),
                    self._owner(blocker, piece),
                    chess.piece_name(blocker.piece_type),
                    chess.square_name(square).upper(),
                )
        target = self.board.piece_at(to_square)
        if kind == chess.PAWN and target:
            return "A pawn can't capture straight ahead: %s is held by %s %s." % (
                chess.square_name(to_square).upper(),
                self._owner(target, piece),
                chess.piece_name(target.piece_type),
            )
        return None

    def play(self, text):
        """Carry out a typed move (e2e4 or Nf3) on the physical board. Returns notes for the players."""
        return self.play_move(self.parse(text))

    def play_move(self, move):
        """Carry out a legal move on the physical board. Returns notes for the players.

        Every drag is checked before anything moves. If the engraver fails once
        the move has started, MoveInterrupted says which drags happened; the
        grid is left at the position before the move.
        """
        steps = physical_steps(self.board, move, self.graveyard)
        for step in steps:
            self.mover.check(step)

        captured = captured_square(self.board, move)
        removed_by_hand = None
        if captured is not None and self.graveyard is None and self.remove_by_hand:
            removed_by_hand = chess.square_name(captured)
            if self.remove_by_hand(removed_by_hand) is False:
                raise ValueError("Move called off. Nothing was moved.")

        done = 0
        try:
            for step in steps:
                self.mover.run(step)
                done += 1
        except Exception as e:
            raise MoveInterrupted(self._interrupted(move, steps, done, removed_by_hand, e))

        if captured is not None and self.graveyard is not None:
            self.graveyard.next_slot(_color_name(self.board.color_at(captured)))
        notes = []
        if move.promotion:
            notes.append(
                "Promotion: swap the pawn on %s for a %s by hand."
                % (chess.square_name(move.to_square).upper(), chess.piece_name(move.promotion))
            )
        self.board.push(move)
        if self.board.is_checkmate():
            notes.append("Checkmate.")
        elif self.board.is_check():
            notes.append("Check.")
        elif self.board.is_game_over():
            notes.append("Game over: %s" % self.board.result())
        return notes

    def _interrupted(self, move, steps, done, removed_by_hand, error):
        lines = [
            "The move %s %s stopped partway: %s"
            % (chess.square_name(move.from_square).upper(), chess.square_name(move.to_square).upper(), error)
        ]
        for i, step in enumerate(steps):
            state = "done" if i < done else ("may have stopped partway" if i == done else "not started")
            lines.append("  %s to %s: %s" % (place(step.start), place(step.end), state))
        if removed_by_hand:
            lines.append("You took the piece off %s for this capture." % removed_by_hand.upper())
        lines.append(
            "The grid still shows the position before the move. Put the pieces back to match it, "
            "or use put and remove to match the real board."
        )
        return "\n".join(lines)
