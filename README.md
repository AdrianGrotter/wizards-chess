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

## Resetting the board

`reset` in the grid drags every piece back to its starting square, along the lines
between squares so nothing is knocked over. It asks the players to:

1. lift off pieces that have no starting square (such as a second queen from a
   promotion), before anything moves;
2. put back captured pieces by hand, at the end.

When two pieces are on each other's squares, one steps aside to a free square first.
`reset grid` only resets the grid, for when the pieces were set up by hand.

## Calibration

1. Run `python -m wizchess jog`.
2. Move the head under the centre of a1 with `x 10`, `y -5` and so on, then `save a1`.
3. Do the same for h1 and a8 (`save h1`, `save a8`).

Every other square is worked out from those three points, so a board that sits
slightly rotated is still hit dead centre.

## Captured pieces

With `"graveyard_columns": null` in `config.json`, `play` asks a player to lift the captured
piece off its square before the capturing piece moves in. Typing `cancel` there calls the
move off before anything moves.

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
