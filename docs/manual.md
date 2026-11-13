# Wizard's chess: manual

A repurposed laser engraver (Twotrees TTS-55, MKS DLC32 board, GRBL 1.1h) moves an
electromagnet under the board to drag magnetic chess pieces.

## Setup

Dependencies come from the Nix flake:

```sh
nix develop          # or `direnv allow` once, if you use direnv
python -m pytest     # run the tests
```

Plug the engraver in over USB. With `"port": "auto"` in `config.json` the tool finds it by
its USB chip; a named port is used when it exists.

## Running on the ESP32, without a laptop

The ESP32 DevKitC can run the whole game by itself: the rules, the routing and the
engraver control. It reaches the engraver over WiFi and serves a web page with the
board; click a piece and then a square to move it.

```
phone or laptop ──web page──► ESP32 (MicroPython) ──WiFi──► engraver
```

The ESP32 only needs power from its USB port. It prints the page's address there when
it starts, and the page can be reached in two ways:

- on the shared WiFi, at the address it prints (also `http://wizardchess.local/`);
- on the ESP32's own WiFi network (`ap_ssid` and `ap_password` in `esp32/config.json`),
  at `http://192.168.4.1/`. Use this when the shared network keeps devices from
  reaching each other, as guest networks do.

Anyone who can open the page can move the pieces.

When it starts, and after **Reconnect**, the page offers to fix risky engraver settings
and asks whether the head is where the engraver believes it is. Until that is confirmed
nothing moves. **STOP** halts the engraver at once.

Setting up the ESP32 (inside `nix develop`):

1. Flash MicroPython once (the board has octal flash and PSRAM):
   `esptool --port <port> erase-flash` then
   `esptool --port <port> write-flash 0 ESP32_GENERIC_S3-SPIRAM_OCT-<version>.bin`
   from https://micropython.org/download/ESP32_GENERIC_S3/
2. Copy `esp32/config.example.json` to `esp32/config.json` and fill in the WiFi and the
   engraver's address (it is git-ignored).
3. `./esp32/deploy.sh` copies the program and both config files onto the board and
   restarts it. Run it again after changing `config.json`, for example after calibrating.

python-chess is too big for the ESP32, so it uses `esp32/chess.py`, a small version of
the same rules with the same interface. The tests check the two against each other, and
`WIZCHESS_RULES=small python -m pytest` runs the whole suite on the small one.

The engraver takes network commands the way its own web page sends them: each command
is an HTTP request to `/command` on port 80, and its replies arrive on a WebSocket on
port 81. The engraver doesn't restart when a session starts this way, so it keeps track
of the head between sessions.

### The same page from the laptop

```sh
python -m wizchess web          # then open http://localhost:8000/
python -m wizchess --fake web   # practice: nothing really moves
```

This runs the game on the laptop, with the engraver on its USB cable.

### The ESP32 as a plain WiFi cable

With `"mode": "bridge"` in `esp32/config.json` and `"link": "wifi"` in `config.json`,
the terminal commands below run on the laptop and the ESP32 (plugged into the laptop on
its UART port) only carries their G-code to the engraver over WiFi.

## Commands

Add `--fake` before any command to print the G-code instead of moving the engraver.

```sh
python -m wizchess info            # engraver info and the settings that matter
python -m wizchess web             # play from a web page in the browser
python -m wizchess grid            # interactive grid: type A4 C2, chess rules enforced
python -m wizchess jog             # interactive: move the head, drag pieces, calibrate
python -m wizchess outline         # head visits A1, A8, H8, H1 in a circle, one per Enter
python -m wizchess outline cycle   # pulls a piece from A1 round the corners at 50 mm/s
python -m wizchess play            # play a game by typing moves (e2e4 or Nf3)
python -m wizchess goto e4         # head under e4, then back to its corner
python -m wizchess move e2 e4      # drag a piece, no rules (--edges: travel between squares)
python -m wizchess home            # $H, once homing switches are installed
```

## Starting and stopping

The board restarts every time the computer connects, and counts every position from
wherever the head is at that moment. Every command that moves the head therefore
starts by asking whether the head is pushed into its corner, and every session ends by
parking the head there again (`quit`, Ctrl-D or Ctrl-C at a prompt).

Before that question, the tool offers to fix engraver settings that make pieces slip
or drop: laser mode (`$32`) and high acceleration (`$120`/`$121`).

Ctrl-C while the head is moving halts the engraver at once, including moves it had
already queued. Its position is lost after that, so push the head back into its corner
before the next run.

Once homing switches are installed, set `$22=1` on the engraver and
`"homing_switches": true` in `config.json`; sessions then home instead of asking.

## When something goes wrong

- A move is checked from start to end (board edges, machine reach) before anything
  moves, so a refused move never starts.
- If the engraver fails partway through a move, the tool lists which drags happened.
  The grid keeps the position from before the move: put the pieces back, or use
  `put` and `remove` to match the real board.
- An engraver alarm (for example a limit switch) is reported with its reason; `unlock`
  clears it.
- After a reply goes missing, the connection is no longer trusted and every command
  says to restart the tool.

## Slow moves

Add `slow` to a grid move (`B1 C3 slow`) to drag that piece at `slow_feed` from
`config.json`: 1500 mm/min, which is 25 mm/s. The head still travels to the piece at
full speed.

## Routing

The empty head always goes straight to the piece it is fetching, passing under other
pieces if they are in the way. A piece being dragged goes straight to its target whenever
the straight path stays at least half a square from every other piece. That covers most
moves: a pawn stepping forward, a queen along an open diagonal, a rook along an open file.

Only when a piece would pass closer than that (a knight hemmed in at the start, the rook
in castling passing the king, any move with rules off that crosses pieces) does it use the
gutters: it steps diagonally onto the lines between squares, follows them, and steps
diagonally onto its target.

## Moving without rules

`rules off` in the grid lets any piece go to any square (`A1 A8`), for testing and for
fixing up the board. A piece on the target square is parked beside the board first (or
lifted off by hand without a graveyard), the drag follows the usual routing rule below,
and whose turn it is stays unchanged. `rules on` switches the rules back on and points out
anything about the position that a real game couldn't reach.

## Resetting the board

`reset` in the grid drags every piece back to its starting square, following the routing
rule above so nothing is knocked over. It asks the players to:

1. lift off pieces that have no starting square (such as a second queen from a
   promotion), before anything moves;
2. put back by hand any captured piece that isn't parked beside the board, at the end.

When two pieces are on each other's squares, one steps aside to a free square first.
`reset grid` only resets the grid, for when the pieces were set up by hand.

## Calibration

1. Run `python -m wizchess jog`.
2. Move the head under the centre of a1 with `x 10`, `y -5` and so on, then `save a1`.
3. Do the same for h1 and a8 (`save h1`, `save a8`).

Check the result with `outline`, which visits the four corner squares in turn.
`outline cycle` pulls a piece from A1 round the corners nonstop (`--speed` in mm/s,
default 50): Enter pauses at the next corner, Enter again carries on, `quit` stops there.
Every other square is worked out from those three points, so a board that sits
slightly rotated is still hit dead centre.

## Captured pieces

The machine reaches about 300 × 324 mm, so there is a spare strip beyond each side's back
rank. With `graveyard` set in `config.json`, a captured piece is dragged into a row there:
White's below rank 1, Black's above rank 8, half a square (16.5 mm with 33 mm squares) apart, filling from the
middle outwards. A row has 17 places, more than the 15 pieces a side can lose. Pieces
travel along the lines between squares, run along the board's edge, and step straight
out into their place.

`reset` drags parked pieces back to their starting squares too.

Set `"graveyard": null` to have players lift captured pieces off by hand instead; `play`
and `grid` then ask before the capturing piece moves in, and typing `cancel` calls the
move off.

## Engraver settings

`info` shows these, and moving commands offer to fix them:

- `$32=0`: laser mode off, otherwise the magnet may switch off whenever the head stops.
- `$120`/`$121`: acceleration; above 1000 mm/s² pieces tend to slip.
- `$110`/`$111`: top speed, if pieces still slip.

## Layout

| Module | Job | On the ESP32 |
|---|---|---|
| `geometry.py` | square name ↔ millimetres, from the a1/h1/a8 calibration | yes |
| `mover.py` | plans head and piece paths: straight when clear, gutters when not | yes |
| `machine.py` | the engraver as actions (`move_to`, `magnet`, `home`), plus a fake | yes |
| `protocol.py` | GRBL's conversation: send a line, wait for `ok`, read status, stop | yes |
| `wifi.py` | carries that conversation over WiFi | yes |
| `grbl.py` | carries it over USB serial | laptop only |
| `game.py` | chess rules, captures, castling, en passant | yes, on `esp32/chess.py` |
| `reset.py` | plans the drags that put every piece back on its starting square | yes |
| `grid.py`, `session.py` | typed commands and what they do | yes |
| `web.py`, `page.html` | the web page and the server behind it | yes |
| `cli.py` | command line | laptop only |

Positions are sent as machine coordinates (`G53`), so offsets that other software
stored on the engraver don't shift the board.
