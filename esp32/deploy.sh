#!/usr/bin/env bash
# Copies the chess program and its settings onto the ESP32 and restarts it.
# Run inside `nix develop`. MicroPython must already be on the board.
# Only the files that the mode in config.json needs are kept on the ESP32.
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

mode="$(python -c 'import json; print(json.load(open("config.json")).get("mode", "game"))')"
# What talks to the engraver and answers requests; cli, config, grbl, chip and voice need a laptop.
modules=(__init__ machine protocol wifi server)
top=(main.py dfplayer.py)
extra=()
case "$mode" in
  api)
    modules+=(boardapi)
    ;;
  game)
    modules+=(geometry mover game reset grid session sound web)
    top+=(chess.py)
    extra=(page.html)
    ;;
  *)
    echo "esp32/config.json has mode \"$mode\"; use \"game\" or \"api\"." >&2
    exit 1
    ;;
esac

copies=()
keep="'config.json', 'game.json', 'state.json', 'boot.py'"
for file in "${top[@]}"; do
  copies+=(+ cp "$file" ":$file")
  keep+=", '$file'"
done
kept="'placeholder'"
for module in "${modules[@]}"; do
  copies+=(+ cp "../wizchess/$module.py" ":wizchess/$module.py")
  kept+=", '$module.py'"
done
for file in ${extra[@]+"${extra[@]}"}; do
  copies+=(+ cp "../wizchess/$file" ":wizchess/$file")
  kept+=", '$file'"
done
if [ "$mode" = game ]; then
  # The page's pictures.
  mpremote "${connect[@]}" mkdir :wizchess 2>/dev/null || true
  mpremote "${connect[@]}" mkdir :wizchess/assets 2>/dev/null || true
  kept+=", 'assets'"
  for picture in ../wizchess/assets/*; do
    copies+=(+ cp "$picture" ":wizchess/assets/$(basename "$picture")")
  done
fi

mpremote "${connect[@]}" mkdir :wizchess 2>/dev/null || true
mpremote "${connect[@]}" exec "
import os
def clear(path):
    try:
        os.remove(path)
    except OSError:
        for inner in os.listdir(path):
            clear(path + '/' + inner)
        os.rmdir(path)
for name in os.listdir('wizchess'):
    if name not in ($kept):
        clear('wizchess/' + name)
for name in os.listdir():
    if name.endswith('.py') and name not in ($keep):
        os.remove(name)
" \
  + cp config.json :config.json \
  + cp ../config.json :game.json \
  "${copies[@]}" \
  + reset
echo "Copied for \"$mode\" mode. The ESP32 restarts, joins the WiFi and says where it can be reached."
