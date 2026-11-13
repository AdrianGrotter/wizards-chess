# Wizard's chess

A chess board that moves its own pieces. A repurposed laser engraver (Twotrees TTS-55)
carries an electromagnet under the board, and the magnet drags the pieces, which have
small magnets in their bases.

Built at Wootcamp 2026.

## How it works

```
phone or laptop ──web page──► ESP32 ──WiFi──► engraver ──► electromagnet under the board
```

- **The engraver** moves the magnet. The laser is replaced by a 12 V electromagnet,
  switched by the laser's own output.
- **An ESP32** runs the game: the chess rules, the route each piece takes, and the
  commands to the engraver. It serves a web page with the board.
- **You** click a piece and a square on that page. The magnet fetches the piece and
  drags it there. Captured pieces are parked beside the board.
- **Or you talk.** A laptop can listen and pass on moves like "knight to f3".

Pieces go straight when the way is clear and along the lines between squares when
another piece is in the way.

## Try it

Dependencies come from the Nix flake.

```sh
nix develop
python -m wizchess --fake web     # practice in the browser, nothing really moves
python -m wizchess web            # the real board, engraver on USB
python -m pytest                  # tests
```

Then open `http://localhost:8000/`.

To set up the ESP32, copy `esp32/config.example.json` to `esp32/config.json`, fill in
the WiFi details and run `./esp32/deploy.sh`. Its `mode` decides where the game runs:
`game` on the ESP32 itself, played from a phone, or `api` on a laptop that sends the
ESP32 requests.

## More

[docs/manual.md](docs/manual.md) has the details: setup, calibration, every command,
how routing and resetting work, the engraver's settings, and what each file does.

## Known limits

- The engraver can't feel whether a piece followed the magnet. If one slips, the grid on
  screen and the real board disagree until you fix it with `put` and `remove`.
- The pieces attract each other. Dragging one closer than about half a square past
  another can pull both along.
- Promotion needs a hand: swap the pawn for the new piece yourself.
