"""Turns a spoken sentence, as a speech recogniser wrote it down, into something for the board.

The microphone is always open, so a sentence only counts when every word in
it is chess talk; anything else is taken for people chatting and ignored.
"""

PIECE_NAMES = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}

PIECES = {
    "pawn": "p", "pawns": "p", "porn": "p", "pond": "p", "paun": "p",
    "knight": "n", "knights": "n", "night": "n", "nights": "n", "horse": "n",
    "bishop": "b", "bishops": "b",
    "rook": "r", "rooks": "r", "rock": "r", "brook": "r", "rookie": "r", "tower": "r",
    "queen": "q", "queens": "q",
    "king": "k", "kings": "k",
}
LETTERS = {
    "alpha": "a", "alfa": "a", "bravo": "b", "charlie": "c", "delta": "d",
    "echo": "e", "foxtrot": "f", "golf": "g", "hotel": "h",
    "bee": "b", "be": "b", "see": "c", "sea": "c", "dee": "d", "gee": "g", "eff": "f", "ef": "f", "aitch": "h", "age": "h",
}
DIGITS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
}
# Words that sound like a number, counted as one only right after a file's letter.
DIGIT_SOUNDS = {"won": "1", "to": "2", "too": "2", "for": "4", "fore": "4", "ate": "8"}
TAKES = ("takes", "take", "capture", "captures", "x", "times")
PROMOTES = ("promote", "promotes", "promoting", "promotion", "equals", "becomes")
FILLER = (
    "the", "my", "a", "please", "move", "moves", "go", "goes", "play", "plays", "to", "on", "from", "at", "and",
    "then", "into", "onto", "with", "now", "um", "uh", "up", "piece", "square", "check", "mate", "checkmate", "side",
    "one",
)
YES = ("yes", "yeah", "yep", "yup", "sure", "okay", "ok", "correct", "confirm", "confirmed", "done", "right")
NO = ("no", "nope", "nah", "cancel", "don't", "dont", "wrong")
STOP = ("stop", "halt", "freeze")
CANCEL = ("cancel", "never", "mind", "nevermind", "forget", "it")
CASTLE = ("castle", "castles", "castling")
KINGSIDE = ("kingside", "short")
QUEENSIDE = ("queenside", "long")


class Heard:
    """What a sentence means for the board.

    kind is "command" (value is a line for the board, spoken says it back),
    "answer" (value is True or False, for the board's question), "stop", or
    "say" (spoken is a reply for the players, nothing goes to the board).
    """

    def __init__(self, kind, value=None, spoken=""):
        self.kind = kind
        self.value = value
        self.spoken = spoken

    def __eq__(self, other):
        return isinstance(other, Heard) and (self.kind, self.value) == (other.kind, other.value)

    def __repr__(self):
        return "Heard(%r, %r, %r)" % (self.kind, self.value, self.spoken)


def words(text):
    """The sentence as lower-case words, with squares like e4 joined into one word."""
    raw = []
    word = ""
    for ch in text.lower().replace("'", "") + " ":
        if ch.isalpha():
            word += ch
            continue
        if word:
            if ch.isdigit() and len(word) == 2 and word not in LETTERS and word[1] in "abcdefgh":
                raw.append(word[0])
                word = word[1]
            raw.append(word)
            word = ""
        if ch.isdigit():
            raw.append(ch)
    out = []
    for token in raw:
        token = LETTERS.get(token, token)
        before = out[-1] if out else ""
        digit = DIGITS.get(token) or (token if token in "12345678" else None)
        after_file = len(before) == 1 and before in "abcdefgh"
        if digit is None and after_file:
            digit = DIGIT_SOUNDS.get(token)
        if digit and after_file:
            out[-1] = before + digit
        else:
            out.append(token)
    return out


def _is_square(word):
    return len(word) == 2 and word[0] in "abcdefgh" and word[1] in "12345678"


def _is_chess_talk(tokens):
    for token in tokens:
        known = (
            _is_square(token) or token in PIECES or token in TAKES or token in PROMOTES or token in FILLER
            or token in CASTLE or token in KINGSIDE or token in QUEENSIDE
            or (len(token) == 1 and token in "abcdefgh")
        )
        if not known:
            return False
    return True


def _name(symbol):
    return PIECE_NAMES[symbol.lower()]


def _describe(start, end, pieces):
    mover = _name(pieces[start]) if start in pieces else "piece"
    if end in pieces:
        return "%s takes %s on %s." % (mover.capitalize(), _name(pieces[end]), end.upper())
    return "%s to %s." % (mover.capitalize(), end.upper())


class Interpreter:
    """Follows the conversation: remembers what it last asked the players."""

    def __init__(self):
        self.choices = None
        self.confirming = None

    def hear(self, text, state):
        """What text means given the board's state (as the web page gets it), or None to ignore it."""
        tokens = words(text)
        if not tokens:
            return None
        if all(t in STOP or t in ("it", "now", "the", "board") for t in tokens) and any(t in STOP for t in tokens):
            self.choices = self.confirming = None
            return Heard("stop", spoken="Stopping.")

        verdict = None
        if all(t in YES for t in tokens):
            verdict = True
        elif all(t in NO for t in tokens):
            verdict = False
        if state.get("question"):
            return None if verdict is None else Heard("answer", verdict)
        if self.confirming is not None:
            command, self.confirming = self.confirming, None
            if verdict is True:
                return command
            if verdict is False:
                return Heard("say", spoken="Okay, leaving it.")
        if self.choices is not None and all(t in CANCEL for t in tokens):
            self.choices = None
            return Heard("say", spoken="Okay, never mind.")

        if tokens in (["new", "game"], ["reset"], ["reset", "the", "board"], ["start", "a", "new", "game"]):
            self.confirming = Heard("command", "reset", "Starting a new game.")
            return Heard("say", spoken="Start a new game? Say yes or no.")
        if not _is_chess_talk(tokens):
            return None
        return self._move(tokens, state)

    def _move(self, tokens, state):
        pieces = state.get("pieces", {})
        legal = [(start, end) for start, ends in state.get("moves", {}).items() for end in ends]
        squares = [t for t in tokens if _is_square(t)]
        files = [t for t in tokens if len(t) == 1 and t in "bcdefgh"]

        promotion = None
        kinds = []
        promoting = False
        for token in tokens:
            if token in PROMOTES:
                promoting = True
            elif token in PIECES:
                if promoting:
                    promotion = PIECES[token]
                else:
                    kinds.append(PIECES[token])

        if self.choices is not None:
            choices, self.choices = self.choices, None
            picked = [c for c in choices if c[0] in squares or c[0][0] in files]
            if len(picked) == 1:
                return self._command(picked[0], pieces, promotion)

        if any(t in CASTLE for t in tokens):
            return self._castle(tokens, pieces, legal)
        if len(squares) >= 2:
            if len(kinds) > 1 and promotion is None:
                promotion = kinds[-1]
            return self._command((squares[0], squares[1]), pieces, promotion)
        if not state.get("rules", True):
            return None

        taking = any(t in TAKES for t in tokens)
        if len(squares) == 1:
            target = squares[0]
            candidates = [m for m in legal if m[1] == target]
            if len(kinds) > 1 and promotion is None and target[1] in "18" and kinds[0] == "p":
                promotion = kinds[1]
            kind = kinds[0] if kinds else None
            wanted = "%s can go to %s" % (_name(kind) if kind else "pawn", target.upper())
        elif len(kinds) == 2 and taking:
            kind = kinds[0]
            candidates = [m for m in legal if m[1] in pieces and pieces[m[1]].lower() == kinds[1]]
            wanted = "%s can take a %s" % (_name(kind), _name(kinds[1]))
        else:
            return None

        if kind is not None:
            candidates = [m for m in candidates if pieces[m[0]].lower() == kind]
        else:
            pawns = [m for m in candidates if pieces[m[0]].lower() == "p"]
            candidates = pawns or candidates
        if files:
            candidates = [m for m in candidates if m[0][0] in files]
        if not candidates:
            return Heard("say", spoken="No %s." % wanted) if kinds else None
        if len(candidates) == 1:
            return self._command(candidates[0], pieces, promotion)
        self.choices = candidates
        starts = sorted({m[0].upper() for m in candidates})
        if len(starts) == 1:
            ends = sorted(m[1].upper() for m in candidates)
            return Heard("say", spoken="Which one: %s?" % " or ".join(ends))
        name = _name(pieces[candidates[0][0]])
        return Heard("say", spoken="Which %s: the one on %s?" % (name, " or ".join(starts)))

    def _castle(self, tokens, pieces, legal):
        castlings = [
            m for m in legal
            if pieces[m[0]].lower() == "k" and abs(ord(m[0][0]) - ord(m[1][0])) == 2
        ]
        side = None
        for i, token in enumerate(tokens):
            if token in KINGSIDE or (token == "king" and tokens[i + 1:i + 2] == ["side"]):
                side = "g"
            if token in QUEENSIDE or (token == "queen" and tokens[i + 1:i + 2] == ["side"]):
                side = "c"
        if side:
            castlings = [m for m in castlings if m[1][0] == side]
        if not castlings:
            return Heard("say", spoken="Castling is not possible now.")
        if len(castlings) > 1:
            return Heard("say", spoken="Castle on which side: kingside or queenside?")
        start, end = castlings[0]
        return Heard(
            "command", "%s %s" % (start, end), "Castling %s." % ("kingside" if end[0] == "g" else "queenside")
        )

    def _command(self, move, pieces, promotion):
        start, end = move
        line = "%s %s" % (start, end)
        spoken = _describe(start, end, pieces)
        if start in pieces and pieces[start].lower() == "p" and end[1] in "18":
            promotion = promotion if promotion in ("q", "r", "b", "n") else "q"
            line += " " + promotion
            spoken = spoken[:-1] + ", promoting to %s." % _name(promotion)
        return Heard("command", line, spoken)
