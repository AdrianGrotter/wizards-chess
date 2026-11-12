from .geometry import parse_square


class GridSession:
    """Carries out grid commands on a game: the part the terminal and the web page share.

    ask_player(message) shows an instruction for the players and returns
    False if they call the action off.
    """

    def __init__(self, game, slow_feed, ask_player):
        self.game = game
        self.slow_feed = slow_feed
        self.ask_player = ask_player
        self.rules = True
        self.came_from = None

    @property
    def machine(self):
        return self.game.mover.machine

    def side(self):
        return "White" if self.game.board.turn else "Black"

    def execute(self, command):
        """Run one command tuple from grid.parse_command. Returns notes for the players.

        Raises ValueError or MachineError with a message for the players.
        """
        game = self.game
        kind = command[0]
        notes = []
        if kind == "reset" and command[1] == "grid":
            game.reset()
            self.came_from = None
        elif kind == "reset":
            self.came_from = None
            notes = game.reset_pieces(self.ask_player)
            game.mover.park(game.occupied())
        elif kind == "park":
            game.mover.park(game.occupied())
        elif kind == "unlock":
            self.machine.unlock()
            notes.append("Alarm cleared.")
        elif kind == "clear":
            game.clear()
            self.came_from = None
        elif kind == "put":
            game.put(command[1], command[2])
        elif kind == "remove":
            game.remove(command[1])
        elif kind == "turn":
            game.set_turn(command[1])
        elif kind == "rules":
            self.rules = command[1] == "on"
            notes.append(
                "Moves follow the chess rules again." if self.rules
                else "Rules are off: any piece can go to any square. Type 'rules on' to go back."
            )
            if self.rules:
                notes.extend("Note: %s." % p for p in game.problems())
        elif kind in ("goto", "move"):
            restore = game.mover.dragging_at(self.slow_feed) if command[-1] else None
            try:
                if kind == "goto":
                    game.mover.goto(parse_square(command[1]), game.occupied())
                    self.machine.wait_until_idle()
                else:
                    _, start, end, promotion, _ = command
                    if self.rules:
                        notes = game.play_move(game.move_between(start, end, promotion))
                    else:
                        notes = game.free_move(start, end)
                    self.came_from = start
            finally:
                if restore:
                    restore()
        if kind in ("clear", "put", "remove", "turn"):
            notes.extend("Note: %s." % p for p in game.problems())
        return notes
