"""Which sound belongs to which moment of the game.

A sound player has play(name), which starts a sound at once and drops
anything still waiting, then(name), which plays after whatever is playing,
and service(), called regularly so waiting sounds get their turn.
"""
import chess

MOVE_SOUNDS = {
    chess.PAWN: "pawn_move",
    chess.KNIGHT: "knight_move",
    chess.BISHOP: "bishop_move",
    chess.ROOK: "rook_move",
    chess.QUEEN: "queen_move",
    chess.KING: "king_move",
}


class Silent:
    def play(self, name):
        pass

    def then(self, name):
        pass

    def service(self):
        pass


def for_drag(piece):
    """The sound for a piece dragged with the rules off, or None when the square is empty."""
    return None if piece is None else MOVE_SOUNDS[piece.piece_type]


def before_move(board, move):
    """The sound for a legal move that is about to be made on board."""
    if board.is_castling(move):
        return "castling"
    if board.is_capture(move):
        return "capture"
    return MOVE_SOUNDS[board.piece_at(move.from_square).piece_type]


def after_move(board, move):
    """The sounds for what a move led to, in the order to play them; board is the position after it."""
    sounds = ["promotion"] if move.promotion else []
    if board.is_checkmate():
        return sounds + ["checkmate", "win"]
    if board.is_game_over():
        return sounds + ["draw"]
    return sounds + ["check" if board.is_check() else "your_turn"]
