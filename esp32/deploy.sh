#!/usr/bin/env bash
# Copies the WiFi bridge and its settings onto the ESP32 and restarts it.
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

mpremote "${connect[@]}" cp config.json :config.json + cp main.py :main.py + reset
echo "Bridge copied. The ESP32 restarts and joins the WiFi."
