# Wizard chess

A repurposed laser engraver (Twotrees TTS-55, MKS DLC32 board, GRBL 1.1h) moves an
electromagnet under the board to drag magnetic chess pieces.

## Setup

Dependencies come from the Nix flake:

```sh
nix develop          # or `direnv allow` once, if you use direnv
python -m pytest     # run the tests
```

Plug the engraver in over USB. The port is set in `config.json` (`/dev/cu.usbserial-2140`).

## Commands

Add `--fake` before any command to print the G-code instead of moving the engraver.

```sh
python -m wizchess info            # engraver info and the settings that matter
python -m wizchess grid            # interactive grid: type A4 -> C2 to drag a piece
python -m wizchess jog             # interactive: move the head, drag pieces, calibrate
python -m wizchess play            # play a game by typing moves (e2e4 or Nf3)
python -m wizchess goto e4         # head under e4, magnet off
python -m wizchess move e2 e4      # drag a piece, no rules (--edges: travel between squares)
python -m wizchess home            # $H, once homing switches are installed
```

## Zero position

The board restarts every time the computer connects, and it treats wherever the head
is at that moment as (0, 0). Until the homing switches are installed:

1. Push the head by hand into the corner it should count from, before connecting.
2. Do a whole session in one command (`jog` or `play`). Every new command reconnects
   and resets (0, 0).

Once the switches are in, set `$22=1` on the engraver and `"homing_switches": true` in
`config.json`, and start each session with homing.

## Calibration

1. Run `python -m wizchess jog`.
2. Move the head under the centre of a1 with `x 10`, `y -5` and so on, then `save a1`.
3. Do the same for h8 and `save h8`.

All other squares are worked out from those two points. If the files (a–h) run along the
machine's Y axis instead of X, set `"files_along": "y"` in `config.json`.

## Captured pieces

With `"graveyard_columns": null` in `config.json`, `play` asks a player to lift the captured
piece off its square before the capturing piece moves in.

## Engraver settings

`info` warns about these:

- `$32=0`: laser mode off, otherwise the magnet switches off whenever the head stops.
- `$110`/`$111` and `$120`/`$121`: lower speed and acceleration if pieces slip.

## Layout

| Module | Job | Runs on ESP32 later? |
|---|---|---|
| `geometry.py` | square name ↔ millimetres, from the a1/h8 calibration | yes, as is |
| `mover.py` | plans the magnet path for one piece and drives it | yes, as is |
| `machine.py` | the engraver as actions (`move_to`, `magnet`, `home`), plus a fake | yes, as is |
| `grbl.py` | sends those actions over USB serial | replace with UART/WiFi |
| `game.py` | chess rules (python-chess), captures, castling, en passant | needs a lighter chess library |
| `cli.py` | command line | laptop only |

Positions are sent as machine coordinates (`G53`), so offsets that other software
stored on the engraver don't shift the board.
