# Wizard chess

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

## Commands

Add `--fake` before any command to print the G-code instead of moving the engraver.

```sh
python -m wizchess info            # engraver info and the settings that matter
python -m wizchess grid            # interactive grid: type A4 C2, chess rules enforced
python -m wizchess jog             # interactive: move the head, drag pieces, calibrate
python -m wizchess outline         # head visits A1, A8, H8, H1 in a circle, one per Enter
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

Add `slow` to a grid move or head move (`B1 C3 slow`, `A4 slow`) to run that one move at
`slow_feed` from `config.json`: 1500 mm/min, which is 25 mm/s, for both the head's travel
and the drag.

## Moving without rules

`rules off` in the grid lets any piece go to any square (`A1 A8`), for testing and for
fixing up the board. A piece on the target square is parked beside the board first (or
lifted off by hand without a graveyard), every drag runs along the lines between squares,
and whose turn it is stays unchanged. `rules on` switches the rules back on and points out
anything about the position that a real game couldn't reach.

## Resetting the board

`reset` in the grid drags every piece back to its starting square, along the lines
between squares so nothing is knocked over. It asks the players to:

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

| Module | Job | Runs on ESP32 later? |
|---|---|---|
| `geometry.py` | square name ↔ millimetres, from the a1/h1/a8 calibration | yes, as is |
| `mover.py` | plans head and piece paths along the lines between squares | yes, as is |
| `machine.py` | the engraver as actions (`move_to`, `magnet`, `home`), plus a fake | yes, as is |
| `grbl.py` | sends those actions over USB serial | replace with UART/WiFi |
| `game.py` | chess rules (python-chess), captures, castling, en passant | needs a lighter chess library |
| `reset.py` | plans the drags that put every piece back on its starting square | yes, with a lighter chess library |
| `cli.py` | command line | laptop only |

Positions are sent as machine coordinates (`G53`), so offsets that other software
stored on the engraver don't shift the board.
