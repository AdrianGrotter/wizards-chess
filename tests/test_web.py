import json
import threading
import time

import pytest

from wizchess import web
from wizchess.grid import parse_command
from wizchess.machine import FakeMachine, GcodeMachine

CFG = {
    "board": {"a1": [34.5, 44.5], "h1": [265.5, 44.5], "a8": [34.5, 275.5]},
    "travel_feed": 6000, "drag_feed": 6000, "slow_feed": 1500,
    "graveyard": {"white_row": -1, "black_row": 8, "spacing": 0.5},
}


class Conn:
    def __init__(self, request):
        self.request = request
        self.sent = b""

    def recv(self, size):
        chunk, self.request = self.request[:size], self.request[size:]
        return chunk

    def sendall(self, data):
        self.sent += data

    def json(self):
        return json.loads(self.sent.split(b"\r\n\r\n", 1)[1])


def started(machine=None):
    app = web.App(CFG, machine or FakeMachine((300, 320), 1000, echo=False))
    threading.Thread(target=app.run, daemon=True).start()
    return app


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def play(app, text):
    wait_for(lambda: not app.busy)
    assert app.submit(text) == (True, "")
    wait_for(lambda: not app.busy and app.pending is None)


def post(app, path, body=""):
    conn = Conn(("POST %s HTTP/1.1\r\nContent-Length: %d\r\n\r\n%s" % (path, len(body), body)).encode())
    web.handle(conn, app)
    return conn.json()


def test_a_game_is_played_through_commands():
    app = started()
    for text in ["e2 e4", "d7 d5", "e4 d5"]:
        play(app, text)
    state = app.state()
    assert state["pieces"]["d5"] == "P"
    assert state["parked"] == {"white": "", "black": "p"}
    assert state["status"] == "Black to move"
    assert state["came_from"] == "e4"
    assert state["ready"] and not state["busy"]


def test_rule_breaks_land_in_the_log_as_errors():
    app = started()
    play(app, "e2 e5")
    assert app.state()["log"][-1] == {"n": 2, "text": "A pawn can't move from E2 to E5.", "error": True}


def test_typing_mistakes_are_answered_at_once():
    app = started()
    accepted, message = app.submit("zz")
    assert not accepted and "Unknown command 'zz'" in message


def test_page_and_state_are_served():
    app = started()
    wait_for(lambda: not app.busy)
    page = Conn(b"GET / HTTP/1.1\r\nHost: board\r\n\r\n")
    web.handle(page, app)
    assert page.sent.startswith(b"HTTP/1.0 200 OK") and b"<title>Wizard's chess</title>" in page.sent
    state = Conn(b"GET /state HTTP/1.1\r\n\r\n")
    web.handle(state, app)
    assert state.json()["status"] == "White to move"
    assert post(app, "/command", "e2 e4") == {"ok": True, "message": ""}
    assert post(app, "/stop")["ok"] in (True, False)
    missing = Conn(b"GET /nothing HTTP/1.1\r\n\r\n")
    web.handle(missing, app)
    assert missing.sent.startswith(b"HTTP/1.0 404")


class SlowMachine(FakeMachine):
    """A move that takes until someone interrupts it, like a long drag."""

    def send(self, line, timeout=None):
        if line.startswith("G53"):
            deadline = time.monotonic() + 5
            while not self.interrupted and time.monotonic() < deadline:
                time.sleep(0.01)
            if self.interrupted:
                raise web.MachineError("Stopped.")
        return super().send(line, timeout)


def test_busy_board_refuses_commands_and_stop_halts_it():
    app = started(SlowMachine((300, 320), 1000, echo=False))
    wait_for(lambda: not app.busy)
    assert app.submit("e2 e4") == (True, "")
    wait_for(lambda: app.busy)
    assert app.submit("d2 d4") == (False, "The board is still busy with the last command.")
    assert app.stop() == (True, "")
    wait_for(lambda: not app.busy)
    assert app.machine.lines[-1] == "<stop>"
    assert not app.ready
    assert "Stopped. The head's position is lost" in app.state()["log"][-1]["text"]
    assert app.state()["pieces"]["e2"] == "P"
    play(app, "e2 e4")
    assert "hasn't been confirmed" in app.state()["log"][-1]["text"]


class Engraver(GcodeMachine):
    """A real machine as far as the app can tell: it has settings and a position to confirm."""

    def __init__(self):
        super().__init__((300, 320), 1000)
        self.lines = []
        self.out_of_step = False

    def send(self, line, timeout=None):
        self.lines.append(line)
        return []

    def settings(self):
        return {"32": "1", "120": "3000.000", "121": "500.000"}

    def position(self):
        return (0.0, 0.0)


def answer(app, yes):
    wait_for(lambda: app.question is not None)
    question = app.question["text"]
    app.give_answer(yes)
    wait_for(lambda: app.question is None or app.question["text"] != question)
    return question


def test_start_offers_safer_settings_and_asks_where_the_head_is():
    app = started(Engraver())
    assert "Laser mode is on" in answer(app, True)
    assert "X acceleration is 3000" in answer(app, False)
    assert "Is the head really there?" in answer(app, True)
    wait_for(lambda: not app.busy)
    assert app.machine.lines == ["$32=0"]
    assert app.ready


def test_unconfirmed_head_blocks_moves_but_not_grid_edits():
    app = started(Engraver())
    for _ in range(3):
        answer(app, False)
    wait_for(lambda: not app.busy)
    assert not app.ready
    assert "switch the engraver off and on again" in app.state()["log"][-1]["text"]
    play(app, "e2 e4")
    assert "hasn't been confirmed" in app.state()["log"][-1]["text"]
    play(app, "remove e2")
    assert "e2" not in app.state()["pieces"]


def test_reset_instructions_wait_for_the_players():
    app = started()
    play(app, "put e4 Q")
    wait_for(lambda: not app.busy)
    assert app.submit("reset") == (True, "")
    assert "Take these pieces off the board: white queen on E4" in answer(app, True)
    wait_for(lambda: not app.busy)
    assert "e4" not in app.state()["pieces"]


def test_reset_grid_forgets_the_captured_pieces():
    app = started()
    for text in ["e2 e4", "d7 d5", "e4 d5", "reset grid"]:
        play(app, text)
    assert app.state()["parked"] == {"white": "", "black": ""}


class Dropping(Engraver):
    def connect(self):
        self.out_of_step = False
        self.head = self.position()


def test_dropped_connection_is_reopened_without_asking_again():
    app = started(Dropping())
    for _ in range(3):
        answer(app, True)
    wait_for(lambda: not app.busy)
    app.machine.out_of_step = True
    play(app, "e2 e4")
    assert app.ready and app.state()["pieces"]["e4"] == "P"
    assert any(entry["text"] == "Reconnected to the engraver." for entry in app.state()["log"])


def test_state_lists_the_legal_moves_of_each_piece():
    app = started()
    wait_for(lambda: not app.busy)
    moves = app.state()["moves"]
    assert sorted(moves["e2"]) == ["e3", "e4"] and sorted(moves["g1"]) == ["f3", "h3"]
    assert "e1" not in moves and "e7" not in moves
    play(app, "rules off")
    assert app.state()["moves"] == {}
