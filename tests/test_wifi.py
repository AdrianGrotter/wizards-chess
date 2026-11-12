import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest

from wizchess.protocol import GrblError
from wizchess.wifi import WifiMachine


class FakeEngraver:
    """Stands in for the engraver's network interface: commands by HTTP, replies on a WebSocket."""

    def __init__(self):
        self.lines = []
        self.state = "Idle"
        self.ws = None
        self.http = self._listen()
        self.websocket = self._listen()
        threading.Thread(target=self._serve_websocket, daemon=True).start()
        threading.Thread(target=self._serve_http, daemon=True).start()

    def _listen(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        return server

    def port(self, server):
        return server.getsockname()[1]

    def _read_head(self, conn):
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(1024)
        return head.decode()

    def _frame(self, opcode, payload):
        self.ws.sendall(bytes([0x80 | opcode, len(payload)]) + payload)

    def _serve_websocket(self):
        while True:
            conn, _ = self.websocket.accept()
            self._read_head(conn)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n")
            self.ws = conn
            self._frame(1, b"CURRENT_ID:3")

    def _serve_http(self):
        while True:
            conn, _ = self.http.accept()
            query = parse_qs(urlparse(self._read_head(conn).split(" ")[1]).query)
            assert query["PAGEID"] == ["3"]
            conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
            conn.close()
            for line in query["commandText"][0].split("\n"):
                for chunk in self._reply(line):
                    self._frame(2, chunk)

    def _reply(self, text):
        if text == "?":
            return [b"<%s|MPos:12.000,34.000,0.000|FS:0,0>\r\n" % self.state.encode()]
        if text == "!":
            self.state = "Hold:0"
            return []
        if text == "\x18":
            self.state = "Idle"
            return [b"\r\nGrbl 1.1h ['$' for help]\r\n"]
        self.lines.append(text)
        if text == "$$":
            return [b"$32=1\r\n$120=", b"500.000\r\nok\r\n"]
        if text == "G1 X999":
            return [b"error:2\r\n"]
        return [b"ok\r\n"]


@pytest.fixture
def engraver():
    return FakeEngraver()


def connect(engraver):
    machine = WifiMachine(
        "127.0.0.1", (300, 320), 1000,
        http_port=engraver.port(engraver.http), ws_port=engraver.port(engraver.websocket), timeout=2,
    )
    machine.connect()
    return machine


def test_connecting_reads_the_head_position(engraver):
    machine = connect(engraver)
    assert machine.head == (12.0, 34.0)
    assert engraver.lines == ["G21", "G90"]


def test_commands_wait_for_ok_and_settings_are_read(engraver):
    machine = connect(engraver)
    machine.move_to(50, 60, 6000)
    machine.magnet(True)
    machine.flush()
    assert engraver.lines[-2:] == ["G53 G1 X50.00 Y60.00 F6000", "M3 S1000"]
    assert machine.settings() == {"32": "1", "120": "500.000"}
    with pytest.raises(GrblError, match="rejected 'G1 X999'"):
        machine.send("G1 X999")
        machine.send("G4 P0")
        machine.flush()


def test_stop_holds_then_resets_and_keeps_the_position(engraver):
    machine = connect(engraver)
    machine.stop()
    assert engraver.state == "Idle"
    assert machine.head == (12.0, 34.0)
    assert not machine.out_of_step


def test_interrupt_ends_a_wait_from_another_thread(engraver):
    machine = connect(engraver)
    engraver._reply = lambda text: []
    threading.Timer(0.3, machine.interrupt).start()
    with pytest.raises(GrblError, match="Stopped"):
        machine.send("G4 P100", timeout=20)
        machine.flush()


def test_unreachable_engraver_has_a_clear_message():
    spare = socket.socket()
    spare.bind(("127.0.0.1", 0))
    port = spare.getsockname()[1]
    spare.close()
    machine = WifiMachine("127.0.0.1", (300, 320), 1000, http_port=port, ws_port=port)
    with pytest.raises(GrblError, match="Can't reach the engraver"):
        machine.connect()


def test_idle_answers_the_engravers_pings(engraver):
    machine = connect(engraver)
    engraver._frame(9, b"hello")
    for _ in range(20):
        machine.idle()
        time.sleep(0.01)
    engraver.ws.settimeout(2)
    pong = engraver.ws.recv(64)
    assert pong[0] == 0x8A and len(pong) == 2 + 4 + 5


def test_idle_notices_a_dropped_connection(engraver):
    machine = connect(engraver)
    engraver.ws.close()
    for _ in range(50):
        machine.idle()
    assert machine.out_of_step


def test_a_connection_that_died_quietly_is_reopened_before_use(engraver):
    machine = connect(engraver)
    machine.alive_seconds = 0.3
    dead, engraver.ws = engraver.ws, socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    engraver.ws.connect(("127.0.0.1", 9))
    machine.last_heard -= 60
    machine.send("G4 P0")
    machine.flush()
    assert engraver.lines[-3:] == ["G21", "G90", "G4 P0"]
    assert machine.head == (12.0, 34.0)
    dead.close()


def test_commands_are_sent_without_waiting_but_never_more_than_the_window(engraver):
    machine = connect(engraver)
    held = threading.Event()
    reply = engraver._reply

    def slow(text):
        if text != "?":
            held.wait(2)
        return reply(text)

    engraver._reply = slow
    lines = ["G53 G1 X%d.00 Y10.00 F6000" % x for x in range(10, 16)]
    threading.Timer(0.5, held.set).start()
    for line in lines:
        machine.send(line)
        assert sum(len(l) + 1 for l in machine.unanswered) <= machine.window
    assert len(machine.unanswered) > 1
    machine.wait_until_idle()
    assert machine.unanswered == []
    assert engraver.lines[-7:] == lines + ["G4 P0"]
