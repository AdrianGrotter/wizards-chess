"""Plays the game's sounds on a DFPlayer mini wired to the ESP32.

The player picks a file by the four-digit number its name starts with, in
the mp3 folder of its SD card: mp3/0008_capture.mp3 is number 8.
"""
import time

import machine

NUMBERS = {
    "start": 1,
    "pawn_move": 2,
    "knight_move": 3,
    "bishop_move": 4,
    "rook_move": 5,
    "queen_move": 6,
    "king_move": 7,
    "capture": 8,
    "invalid_move": 9,
    "win": 10,
    "check": 11,
    "checkmate": 12,
    "castling": 13,
    "promotion": 14,
    "draw": 15,
    "your_turn": 16,
}
SET_VOLUME = 0x06
PLAY_MP3_NUMBER = 0x12
MAX_WAITING = 4
# The busy pin takes a moment to drop after a play command.
BUSY_LAG_MS = 500


class Player:
    def __init__(self, tx, rx, busy, volume):
        self.uart = machine.UART(1, baudrate=9600, tx=tx, rx=rx, timeout=100)
        self.busy = machine.Pin(busy, machine.Pin.IN)
        self.waiting = []
        self.started = time.ticks_ms()
        time.sleep_ms(200)
        self._send(SET_VOLUME, max(0, min(30, int(volume))))
        time.sleep_ms(200)

    def _send(self, command, value=0):
        body = [0xFF, 0x06, command, 0x00, value >> 8, value & 0xFF]
        checksum = (-sum(body)) & 0xFFFF
        self.uart.write(bytes([0x7E] + body + [checksum >> 8, checksum & 0xFF, 0xEF]))
        self.uart.read()

    def _start(self, name):
        self._send(PLAY_MP3_NUMBER, NUMBERS[name])
        self.started = time.ticks_ms()

    def _playing(self):
        # The busy pin is low while a sound plays.
        return self.busy.value() == 0 or time.ticks_diff(time.ticks_ms(), self.started) < BUSY_LAG_MS

    def play(self, name):
        self.waiting = []
        self._start(name)

    def then(self, name):
        if len(self.waiting) < MAX_WAITING:
            self.waiting.append(name)

    def service(self):
        if self.waiting and not self._playing():
            self._start(self.waiting.pop(0))
