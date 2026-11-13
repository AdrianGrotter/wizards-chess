#!/usr/bin/env bash
# Copies the chess program and its settings onto the ESP32 and restarts it.
# Run inside `nix develop`. MicroPython must already be on the board.
set -euo pipefail

cd "$(dirname "$0")"
if [ ! -f config.json ]; then
  echo "esp32/config.json is missing: copy config.example.json and fill in the WiFi details." >&2
  exit 1
fi

port="${1:-auto}"
connect=()
if [ "$port" != "auto" ]; then
  connect=(connect "$port")
fi

# The game's own modules; cli, config and grbl need a laptop.
modules=(__init__ geometry machine mover game reset grid session sound protocol wifi web boardapi)
copies=()
for module in "${modules[@]}"; do
  copies+=(+ cp "../wizchess/$module.py" ":wizchess/$module.py")
done

mpremote "${connect[@]}" mkdir :wizchess 2>/dev/null || true
mpremote "${connect[@]}" \
  cp config.json :config.json \
  + cp ../config.json :game.json \
  + cp main.py :main.py + cp bridge.py :bridge.py + cp chess.py :chess.py + cp dfplayer.py :dfplayer.py \
  "${copies[@]}" \
  + cp ../wizchess/page.html :wizchess/page.html \
  + reset
echo "Copied. The ESP32 restarts, joins the WiFi and says where to open the page."
