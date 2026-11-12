"""WiFi bridge between the laptop and the engraver.

Runs on the ESP32 under MicroPython. The laptop talks G-code to the ESP32's
USB serial port exactly as it would to the engraver's own USB port; this
script carries it over WiFi.

The engraver's network interface works like its web page: each command is
an HTTP request to /command on port 80, and everything the engraver prints
(ok, errors, status reports) arrives as binary frames on a WebSocket on
port 81. The PAGEID sent with each command is the id the WebSocket was given,
so the replies come to this connection. Settings come from config.json.
"""
import binascii
import json
import os
import select
import socket
import sys
import time

import network

# GRBL's real-time commands act on their own, without a newline.
REALTIME = b"?!~\x18"


def say(text):
    sys.stdout.write("[bridge] %s\r\n" % text)


def load_config():
    with open("config.json") as f:
        return json.load(f)


def connect_wifi(ssid, password, seconds=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
        deadline = time.ticks_add(time.ticks_ms(), seconds * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                raise OSError("could not join WiFi %r" % ssid)
            time.sleep_ms(100)
    return wlan.ifconfig()[0]


def _address(host, port):
    return socket.getaddrinfo(host, port)[0][-1]


def _url_encode(text):
    return "".join(c if (c.isalpha() or c.isdigit()) else "%%%02X" % ord(c) for c in text)


class Engraver:
    def __init__(self, host, http_port=80, ws_port=81):
        self.host = host
        self.http_port = http_port
        self.ws = self._open_websocket(ws_port)
        self.page_id = None
        self.pending = b""

    def _open_websocket(self, port):
        sock = socket.socket()
        sock.settimeout(5)
        sock.connect(_address(self.host, port))
        key = binascii.b2a_base64(os.urandom(16)).strip()
        sock.send(
            ("GET / HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             % (self.host, port)).encode()
            + b"Sec-WebSocket-Key: " + key
            + b"\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: arduino\r\n\r\n"
        )
        head = b""
        while b"\r\n\r\n" not in head:
            byte = sock.recv(1)
            if not byte:
                raise OSError("engraver refused the WebSocket")
            head += byte
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise OSError("engraver refused the WebSocket")
        sock.setblocking(False)
        return sock

    def command(self, text):
        """Send one command; its output arrives later on the WebSocket."""
        sock = socket.socket()
        sock.settimeout(5)
        try:
            sock.connect(_address(self.host, self.http_port))
            sock.send(
                ("GET /command?commandText=%s&PAGEID=%s HTTP/1.0\r\n\r\n"
                 % (_url_encode(text), self.page_id or 0)).encode()
            )
            while sock.recv(256):
                pass
        finally:
            sock.close()

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.ws.write(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def read_output(self):
        """Engraver output that has arrived, as bytes; raises OSError when the WebSocket closes."""
        data = self.ws.recv(1024)
        if not data:
            raise OSError("engraver closed the WebSocket")
        self.pending += data
        output = b""
        while len(self.pending) >= 2:
            opcode = self.pending[0] & 0x0F
            length = self.pending[1] & 0x7F
            start = 2
            if length == 126:
                if len(self.pending) < 4:
                    break
                length = (self.pending[2] << 8) | self.pending[3]
                start = 4
            elif length == 127:
                if len(self.pending) < 10:
                    break
                length = int.from_bytes(self.pending[2:10], "big")
                start = 10
            if len(self.pending) < start + length:
                break
            payload = self.pending[start:start + length]
            self.pending = self.pending[start + length:]
            if opcode == 2:
                output += payload
            elif opcode == 1 and payload.startswith(b"CURRENT_ID:"):
                self.page_id = payload.split(b":")[1].decode()
            elif opcode == 9:
                self._send_frame(10, payload)
            elif opcode == 8:
                raise OSError("engraver closed the WebSocket")
        return output


def bridge(engraver):
    usb_in = sys.stdin.buffer
    usb_out = sys.stdout.buffer
    poller = select.poll()
    poller.register(usb_in, select.POLLIN)
    poller.register(engraver.ws, select.POLLIN)
    line = b""
    while True:
        for obj, event in poller.poll(1000):
            if obj is engraver.ws:
                if event & (select.POLLHUP | select.POLLERR):
                    raise OSError("engraver closed the WebSocket")
                output = engraver.read_output()
                if output:
                    usb_out.write(output)
                continue
            byte = usb_in.read(1)
            if not byte:
                continue
            if byte in REALTIME:
                engraver.command(byte.decode())
            elif byte == b"\n":
                text = line.strip().decode()
                line = b""
                if text:
                    engraver.command(text)
            elif byte != b"\r":
                line += byte


def main():
    config = load_config()
    while True:
        engraver = None
        try:
            ip = connect_wifi(config["wifi_ssid"], config["wifi_password"])
            say("WiFi %s, address %s" % (config["wifi_ssid"], ip))
            engraver = Engraver(
                config["engraver_host"], config.get("http_port", 80), config.get("websocket_port", 81)
            )
            say("connected to engraver %s" % config["engraver_host"])
            bridge(engraver)
        except Exception as e:
            say("connection lost (%s), retrying" % e)
            time.sleep(2)
        finally:
            if engraver is not None:
                engraver.ws.close()


main()
