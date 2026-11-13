# Wizard's chess: manual

A repurposed laser engraver (Twotrees TTS-55, MKS DLC32 board, GRBL 1.1h) moves an
electromagnet under the board to drag magnetic chess pieces.

## How the parts fit

```
phone ──web page──► laptop (rules, routes, voice) ──requests──► ESP32 ──WiFi──► engraver
```

- **The laptop** runs the game: the chess rules, the route each piece takes, the web
  page with the board, and voice control.
- **The ESP32** next to the board is a service. It takes requests to move the head,
  switch the magnet and play a sound, and passes them to the engraver over WiFi. It also
  has the speaker and the magnet sensor.
- **The engraver** moves the magnet.

Two other setups still work and are described under [Other setups](#other-setups): the
whole game on the ESP32 with only a phone, and the laptop on the engraver's USB cable.

## Setup

Dependencies come from the Nix flake:

```sh
nix develop          # or `direnv allow` once, if you use direnv
python -m pytest     # run the tests
```

Setting up the ESP32 (inside `nix develop`):

1. Flash MicroPython once (the board has octal flash and PSRAM):
   `esptool --port <port> erase-flash` then
   `esptool --port <port> write-flash 0 ESP32_GENERIC_S3-SPIRAM_OCT-<version>.bin`
   from https://micropython.org/download/ESP32_GENERIC_S3/
2. Copy `esp32/config.example.json` to `esp32/config.json` (it is git-ignored). Fill in
   the WiFi and the engraver's address, and set `"mode": "api"`.
3. `./esp32/deploy.sh` copies what that mode needs onto the ESP32, removes the rest and
   restarts it. Run it again after changing either config file.

The ESP32 only needs power from its USB port. It prints its addresses there when it
starts. It can be reached in two ways:

- on the shared WiFi, at the address it prints (also `http://wizardchess.local/`);
- on the ESP32's own WiFi network (`ap_ssid` and `ap_password` in `esp32/config.json`),
  at `http://192.168.4.1/`. Use this when the shared network keeps devices from
  reaching each other, as guest networks do.

On the laptop, `config.json` needs `"link": "chip"` and the ESP32's address under
`"chip"`. The laptop must be on a network where it can reach that address.

## Playing

```sh
python -m wizchess web --host 0.0.0.0   # then open http://localhost:8000/
python -m wizchess --fake web           # practice: nothing really moves
```

The page shows the board on a wooden plank, a sheet with tabs for the game, the controls,
the sensor and the settings, and a tray with the captured pieces. Its pictures are in
`wizchess/assets/`, and its fonts come from Google Fonts when the browser has internet.

Click a piece and then a square to move it. There is no need to wait for a piece to
arrive: the next moves can be given while it travels, up to four ahead. Each is checked
at once against the position it will meet, the page shows that position straight away,
and the board carries the moves out in order. If one fails or STOP is pressed, the moves
still waiting are dropped. With `--host 0.0.0.0`, phones on the same
network can open the page at the laptop's address too. Anyone who can open the page can
move the pieces.

When it starts, and after **Reconnect**, the page offers to fix risky engraver settings
and asks whether the head is where the engraver believes it is. Until that is confirmed
nothing moves. **STOP** halts the engraver at once. The grid is kept in `state.json`
between runs.

### Playing by voice

The laptop that runs the game can listen on its microphone and pass on what is said, so
a game runs like a conversation. It starts muted; press **Listening** under Voice on the page to switch it on, and **Muted** to switch it off. The page
shows what it is doing, the last sentences it heard with what became of each, and its
latest reply. The microphone is the laptop's, also when the page is open on a phone.

`web` takes `--level` and `--microphone` for it. The same listener runs on its own from
a terminal, against a page anywhere, such as an ESP32 in game mode:

```sh
python -m wizchess voice --board http://192.168.4.1
python -m wizchess voice --typed   # type the sentences, no microphone
```

Speech is recognised on the laptop itself by whisper.cpp, with no internet. It needs a
model file once, in `models/` (git-ignored):

```sh
mkdir -p models && curl -L -o models/ggml-small.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
```

What it understands:

| Say | What happens |
|---|---|
| "knight to f3", "pawn takes d5", "e4" | that move, when exactly one piece can make it |
| "e2 e4", "alpha two alpha four" | from one square to another; with rules off this is the only form |
| "bishop takes knight" | the capture, named by pieces |
| "castle", "castle queenside" | castling |
| "pawn takes a8, promote to knight" | promotion; a queen unless you say otherwise |
| "yes", "no" | answers the board's question |
| "new game" | asks for a yes first |
| "stop" | halts the engraver, about a second after the word |

It listens all the time, so a sentence only counts when every word in it is chess talk;
anything else is taken for chatter. It never speaks: its replies appear on the page and
in the terminal, as text. There it names each move as the move starts, asks which piece
when two could make the move ("Which knight: the one on B1 or F3?"), and shows every
sentence it heard with what it did with it. The terminal version says the replies aloud
only when started with `--aloud`.

Letters like B, D and E sound alike. When it mishears a square, name both squares or use
the spelling alphabet: alpha, bravo, charlie, delta, echo, foxtrot, golf, hotel.
`--level` sets how loud speech must be (default 700 of 32767); raise it in a noisy room.
The STOP button on the page is faster than the word.

## The ESP32's requests

Other devices can use the ESP32's service directly. Requests are JSON over HTTP on port
80; `GET /` lists them. Anything that uses the engraver is a job: one runs at a time,
the request returns the job's number at once, and `GET /status` shows the last job that
finished (`done`) with its `error` or `result`.

| Request | Body | What it does |
|---|---|---|
| `GET /status` | | head position in mm, busy, job, done, error, result, connected, sensor |
| `POST /connect` | | job: connects to the engraver afresh and reads where the head is |
| `POST /run` | `{"actions": [["move", 50, 60, 30000], ["magnet", true], ["dwell", 0.3]]}` | job: carries the actions out in order; a move is x and y in mm and a speed in mm/min |
| `POST /stop` | | halts the engraver at once, magnet off |
| `POST /settings` | | job: the engraver's settings, as the result |
| `POST /set` | `{"name": "120", "value": "500"}` | job: changes one engraver setting |
| `POST /unlock`, `POST /home` | | job: clears an alarm; runs homing |
| `POST /sound` | `{"name": "capture", "queued": false}` | plays a sound from the table below |

The ESP32 checks every move of a request against the machine's reach before any of them
starts, and switches the magnet off when a job fails. Anyone on the network can send
requests; there is no password.

The engraver itself takes network commands the way its own web page sends them: each
command is an HTTP request to `/command` on port 80, and its replies arrive on a
WebSocket on port 81. It doesn't restart when a session starts this way, so it keeps
track of the head between sessions. If it was left paused, connecting ends the pause
and drops the moves that were waiting.

## Sounds

A DFPlayer mini wired to the ESP32 plays a sound for what happens on the board. Its
pins and volume (0 to 30) are under `sound` in `config.json`; without that entry the
game is silent. With the game on a laptop, the laptop tells the ESP32 which sound to
play. The player's SD card needs a folder `mp3` with files whose names start
with a four-digit number; the rest of the name is free:

| Number | Sound | Played |
|---|---|---|
| 1 | start | when the head's position is confirmed |
| 2 to 7 | pawn, knight, bishop, rook, queen, king move | as that piece starts to move |
| 8 | capture | as a capture starts |
| 9 | invalid_move | when a move is refused |
| 10 | win | after the checkmate sound |
| 11 | check | after a move that gives check |
| 12 | checkmate | after a move that ends the game |
| 13 | castling | as castling starts |
| 14 | promotion | after a pawn is promoted |
| 15 | draw | after a move that ends the game in a draw |
| 16 | your_turn | after any other move |

The sound for a move starts with the move and cuts off whatever was still playing; the
sounds for what the move led to wait their turn. macOS adds hidden `._` files when it
copies onto the card, which the player mistakes for sounds: run `dot_clean -m` on the
card afterwards.

## Magnet sensor

With `"magnet_sensor": {"pin": 4}` in `config.json`, the page shows whether a hall
sensor (a 3144) on that pin feels a magnet. Seen from its text side with the legs down,
the sensor's legs go to 3.3 V, ground and the pin. It reacts to one pole only, on its
text side.

## Other setups

### The whole game on the ESP32

With `"mode": "game"` in `esp32/config.json` (and `./esp32/deploy.sh` run again) the
ESP32 runs the game itself and serves the web page, so a phone is all it takes:

```
phone ──web page──► ESP32 (rules, routes) ──WiFi──► engraver
```

Open the ESP32's address in a browser. There is no voice control this way unless a
laptop runs `voice --board` against that address. The grid is kept on the ESP32.

python-chess is too big for the ESP32, so game mode uses `esp32/chess.py`, a small
version of the same rules with the same interface. The tests check the two against each
other, and `WIZCHESS_RULES=small python -m pytest` runs the whole suite on the small
one. Everything the game needs must therefore also run under MicroPython.

### The laptop on the engraver's USB cable

With `"link": "usb"` in `config.json` the laptop talks to the engraver directly and no
ESP32 is needed, but there are no sounds and no sensor. With `"port": "auto"` the tool
finds the engraver by its USB chip; a named port is used when it exists.

The engraver restarts every time the laptop connects this way, and counts every
position from wherever the head is at that moment. See [Starting and stopping](#starting-and-stopping).

## Commands

Add `--fake` before any command to print the G-code instead of moving the engraver.

```sh
python -m wizchess web             # play from a web page in the browser
python -m wizchess voice           # play by talking; see Playing by voice
python -m wizchess info            # engraver info and the settings that matter
python -m wizchess grid            # interactive grid: type A4 C2, chess rules enforced
python -m wizchess jog             # interactive: move the head, drag pieces, calibrate
python -m wizchess outline         # head visits A1, A8, H8, H1 in a circle, one per Enter
python -m wizchess outline cycle   # pulls a piece from A1 round the corners at 50 mm/s
python -m wizchess goto e4         # head under e4, then back to its corner
python -m wizchess move e2 e4      # drag a piece, no rules (--edges: travel between squares)
python -m wizchess home            # $H, once homing switches are installed
```

## Starting and stopping

Nothing moves until the head's position is confirmed, because the engraver has no
switches to find it by itself.

- **Through the ESP32**, the engraver keeps counting between sessions. Each session
  starts by showing where the engraver believes the head is and asking whether that is
  right. If it isn't, push the head into its corner and switch the engraver off and on.
- **On the USB cable**, the engraver restarts with every connection and counts from
  wherever the head is then. Each session starts by asking whether the head is pushed
  into its corner.

Terminal sessions end by parking the head in its corner (`quit`, Ctrl-D or Ctrl-C at a
prompt). Before the position question, the tool offers to fix engraver settings that
make pieces slip or drop: laser mode (`$32`) and high acceleration (`$120`/`$121`).

STOP on the page, or Ctrl-C in a terminal while the head is moving, halts the engraver
at once, including moves it had already queued. If the head was still moving at that
moment its position is lost: push it back into its corner and switch the engraver off
and on before the next run.

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

## Pieces that stop short

Friction makes a dragged piece trail the magnet, so it stops a little short of the
square's centre. How much depends on the surface and the piece, and changes over time.

With `centring_mm` in `config.json`, every drag ends with the magnet spiralling inwards
around the target, three times round, starting that many millimetres out. A trailing
piece is led round on a circle of its own, which closes to nothing as the magnet's
circle shrinks, so it ends within about half a millimetre of the centre whether it
trailed a lot or not at all. Set it a little wider than the worst gap you see; a piece
that trails by more than `centring_mm` still stops short by the difference. The spiral
adds about a second to each drag.

To try values, move the slider on the page's Settings tab, or type `centre 4` in its
text box; it applies from the next drag, and 0 switches it off. Put the value in
`config.json` to keep it, because one set on the page is forgotten when the program
restarts.

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

`rules off` is for testing the board. A move like `A1 A8` then does exactly what it says:
the magnet goes to A1, switches on and drags to A8. Nothing is checked against the grid,
so it works with pieces placed by hand, and from squares the grid shows as empty. The
grid only follows along: a piece it shows on the start square moves to the target and
replaces whatever it showed there. Nothing is parked beside the board. The drag still
goes straight unless the grid shows a piece in the way.

The head must still have a confirmed position, and moves outside the machine's reach
are still refused. `rules on` switches the rules back on and points out anything about
the position that a real game couldn't reach.

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
middle outwards. A row has 17 places, more than the 15 pieces a side can lose.

Pieces pull on each other, so a captured piece takes the way out that passes the fewest
other pieces, even when that is longer. Early in a game that usually means sideways
across the empty middle of the board, out past the a- or h-file, round the corner and
along the row to its place. Later, with pieces spread out and places taken, it picks
whatever way is quietest then, and squeezes between pieces only when there is no better
way. The same goes for pieces that `reset` brings back. This needs the machine to reach
about a square beyond the board; where it can't, the route stays within what it can reach.

`reset` drags parked pieces back to their starting squares too.

Set `"graveyard": null` to have players lift captured pieces off by hand instead; the
game then asks before the capturing piece moves in, and `cancel` calls the move off.

## Engraver settings

`info` shows these, and moving commands offer to fix them:

- `$32=0`: laser mode off, otherwise the magnet may switch off whenever the head stops.
- `$120`/`$121`: acceleration; above 1000 mm/s² pieces tend to slip.
- `$110`/`$111`: top speed, if pieces still slip.

## Layout

The last column says which files the ESP32 gets: in both modes, only with the game on
it, or never.

| Module | Job | On the ESP32 |
|---|---|---|
| `machine.py` | the engraver as actions (`move_to`, `magnet`, `home`), plus a fake | both modes |
| `protocol.py` | GRBL's conversation: send a line, wait for `ok`, read status, stop | both modes |
| `wifi.py` | carries that conversation to the engraver over WiFi | both modes |
| `server.py` | a very small HTTP server | both modes |
| `boardapi.py` | the ESP32 as a service: requests to move, switch the magnet, play sounds | api mode |
| `chip.py` | drives the board through that service | laptop only |
| `grbl.py` | carries GRBL's conversation over USB serial | laptop only |
| `geometry.py` | square name ↔ millimetres, from the a1/h1/a8 calibration | game mode |
| `mover.py` | plans piece paths: straight when clear, gutters when not, quiet ways out | game mode |
| `game.py` | chess rules, captures, castling, en passant | game mode, on `esp32/chess.py` |
| `reset.py` | plans the drags that put every piece back on its starting square | game mode |
| `grid.py`, `session.py` | typed commands and what they do | game mode |
| `sound.py` | which sound belongs to which moment of the game | game mode |
| `web.py`, `page.html` | the web page and the game loop behind it | game mode |
| `heard.py` | turns a spoken sentence into a command for the board | laptop only |
| `voice.py` | microphone, speech recogniser and the replies | laptop only |
| `cli.py` | command line | laptop only |

Positions are sent as machine coordinates (`G53`), so offsets that other software
stored on the engraver don't shift the board.
