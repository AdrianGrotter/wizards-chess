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
        steps.append(Step(grid(captured), graveyard.next_slot(color), via_edges=True))

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

    def play(self, text):
        """Carry out a move on the physical board. Returns notes for the players."""
        move = self.parse(text)
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
