"""The engraver reached over WiFi, without a USB cable.

The engraver's network interface works like its web page: each command is
an HTTP request to /command on port 80, and everything the engraver prints
(ok, errors, status reports) arrives as binary frames on a WebSocket on
port 81. The PAGEID sent with each command is the id the WebSocket was
given, so the replies come to this connection.

Runs under both Python and MicroPython.
"""
import binascii
import os
import select
import socket

from .protocol import GrblError, GrblProtocol, monotonic


def _address(host, port):
    return socket.getaddrinfo(host, port)[0][-1]


def _url_encode(text):
    return "".join(c if (c.isalpha() or c.isdigit()) else "%%%02X" % ord(c) for c in text)


class Engraver:
    def __init__(self, host, http_port=80, ws_port=81):
        self.host = host
        self.http_port = http_port
        self.page_id = None
        self.pending = b""
        self.ws = self._open_websocket(ws_port)
        self.poller = select.poll()
        self.poller.register(self.ws, select.POLLIN)

    def _open_websocket(self, port):
        sock = socket.socket()
        sock.settimeout(5)
        try:
            sock.connect(_address(self.host, port))
            key = binascii.b2a_base64(os.urandom(16)).strip()
            sock.sendall(
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
        except Exception:
            sock.close()
            raise
        return sock

    def command(self, text):
        """Send one command; its output arrives later on the WebSocket."""
        sock = socket.socket()
        sock.settimeout(5)
        try:
            sock.connect(_address(self.host, self.http_port))
            sock.sendall(
                ("GET /command?commandText=%s&PAGEID=%s HTTP/1.0\r\n\r\n"
                 % (_url_encode(text), self.page_id or 0)).encode()
            )
            # The command is on its way once the request is sent; the HTTP
            # reply carries nothing and is only read to let the engraver finish.
            try:
                while sock.recv(256):
                    pass
            except OSError:
                pass
        finally:
            sock.close()

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.ws.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def read_output(self, wait_ms=0):
        """Engraver output arriving within wait_ms, as bytes; OSError when the WebSocket closes."""
        ready = self.poller.poll(wait_ms)
        if not ready:
            return b""
        if ready[0][1] & (select.POLLHUP | select.POLLERR):
            raise OSError("engraver closed the WebSocket")
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

    def close(self):
        try:
            self.ws.close()
        except OSError:
            pass


class WifiMachine(GrblProtocol):
    """Drives a GRBL engraver over WiFi. Call connect() before anything else, and again after a lost connection."""

    restart_hint = "Press Reconnect."
    # A connection that has been quiet this long is checked before it is used:
    # the network can drop it without either end being told.
    quiet_seconds = 5
    alive_seconds = 3

    def __init__(
        self, host, travel_mm, magnet_power, homing_switches=False, http_port=80, ws_port=81, timeout=10.0
    ):
        super().__init__(travel_mm, magnet_power, homing_switches, timeout)
        self.host = host
        self.http_port = http_port
        self.ws_port = ws_port
        self.engraver = None
        self.buffer = b""
        self.head = None
        self.last_heard = 0
        self.silent_message = "The engraver at %s is on the network but did not answer." % host

    def connect(self):
        """Open the connection afresh and read where the engraver says the head is."""
        self.close()
        self.buffer = b""
        self.interrupted = False
        self.out_of_step = False
        self.head = None
        try:
            self.engraver = Engraver(self.host, self.http_port, self.ws_port)
        except OSError as e:
            raise GrblError(
                "Can't reach the engraver at %s over WiFi (%s). Is it switched on and on the same network?"
                % (self.host, e)
            )
        self._wait_until_ready(seconds=15)
        self.setup()
        self.head = self.position()

    def _lost(self):
        self.out_of_step = True
        return GrblError("Lost the WiFi connection to the engraver. Press Reconnect.")

    def _write(self, data):
        if self.engraver is None:
            raise self._lost()
        text = data.decode()
        try:
            self.engraver.command(text.strip() if len(text) > 1 else text)
        except OSError:
            raise self._lost()

    def _take_line(self):
        line, newline, rest = self.buffer.partition(b"\n")
        if not newline:
            return b""
        self.buffer = rest
        return line + b"\n"

    def _readline(self):
        line = self._take_line()
        if line:
            return line
        if self.engraver is None:
            raise self._lost()
        try:
            data = self.engraver.read_output(100)
        except OSError:
            raise self._lost()
        if data:
            self.last_heard = monotonic()
            self.buffer += data
        return self._take_line()

    def _answers(self):
        try:
            self._reset_input()
            self._write(b"?")
            deadline = monotonic() + self.alive_seconds
            while monotonic() < deadline:
                if self._readline().startswith(b"<"):
                    return True
        except GrblError:
            pass
        return False

    def _revive(self):
        """Reopen a connection that went quiet and died, if the head is still where it was left."""
        if self.out_of_step or monotonic() - self.last_heard < self.quiet_seconds or self._answers():
            return
        expected = self.head
        self.connect()
        if expected is not None and (
            self.head is None or max(abs(a - b) for a, b in zip(expected, self.head)) > 0.05
        ):
            self.out_of_step = True
            raise GrblError(
                "The engraver no longer has the head where it was left: it was restarted "
                "or moved by something else. Press Reconnect."
            )

    def send(self, line, timeout=None):
        self._revive()
        return super().send(line, timeout)

    def status(self):
        self._revive()
        return super().status()

    def _reset_input(self):
        self.buffer = b""
        if self.engraver is not None:
            try:
                while self.engraver.read_output(0):
                    pass
            except OSError:
                raise self._lost()

    def idle(self):
        # The engraver drops a WebSocket that stops answering its pings, and
        # pings are only answered while its output is being read.
        if self.engraver is None or self.out_of_step:
            return
        try:
            while self.engraver.read_output(0):
                pass
        except OSError:
            self.out_of_step = True

    def close(self):
        if self.engraver is not None:
            self.engraver.close()
            self.engraver = None
