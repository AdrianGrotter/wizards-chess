import chess

from .mover import Step


def grid(square):
    return (chess.square_file(square), chess.square_rank(square))


class Graveyard:
    """Hands out off-board grid points for captured pieces.

    columns maps "white"/"black" to the file columns their captured
    pieces are lined up in, eight per column from rank 1 upwards.
    """

    def __init__(self, columns):
        self.columns = columns
        self.count = {"white": 0, "black": 0}

    def next_slot(self, color):
        index = self.count[color]
        columns = self.columns[color]
        if index >= 8 * len(columns):
            raise RuntimeError("No room left for captured %s pieces" % color)
        self.count[color] += 1
        return (columns[index // 8], index % 8)


def captured_square(board, move):
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
    return move.to_square


def physical_steps(board, move, graveyard):
    """The piece drags needed to carry out a legal move on the given board.

    Without a graveyard, captured pieces are left for a player to remove.
    """
    steps = []
    captured = captured_square(board, move)
    if captured is not None and graveyard is not None:
        color = "white" if board.color_at(captured) == chess.WHITE else "black"
        steps.append(
            Step(grid(captured), graveyard.next_slot(color), via_edges=True, leaves_board=True)
        )

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
        """remove_by_hand(square_name) is called before a capture when there is no graveyard."""
        self.board = chess.Board()
        self.mover = mover
        self.graveyard = graveyard
        self.remove_by_hand = remove_by_hand

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
        raise ValueError(
            "A %s can't move from %s to %s."
            % (chess.piece_name(piece.piece_type), start.upper(), end.upper())
        )

    def play(self, text):
        """Carry out a typed move (e2e4 or Nf3) on the physical board. Returns notes for the players."""
        return self.play_move(self.parse(text))

    def play_move(self, move):
        """Carry out a legal move on the physical board. Returns notes for the players."""
        captured = captured_square(self.board, move)
        if captured is not None and self.graveyard is None and self.remove_by_hand:
            self.remove_by_hand(chess.square_name(captured))
        for step in physical_steps(self.board, move, self.graveyard):
            self.mover.run(step)
        notes = []
        if move.promotion:
            notes.append(
                "Promotion: swap the pawn on %s for a %s by hand."
                % (chess.square_name(move.to_square), chess.piece_name(move.promotion))
            )
        self.board.push(move)
        if self.board.is_checkmate():
            notes.append("Checkmate.")
        elif self.board.is_check():
            notes.append("Check.")
        elif self.board.is_game_over():
            notes.append("Game over: %s" % self.board.result())
        return notes
