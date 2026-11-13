import json
import socket
import threading
import time
import urllib.request

import pytest

from wizchess import boardapi, server, web
from wizchess.chip import ChipMachine
from wizchess.geometry import Geometry
from wizchess.machine import FakeMachine, MachineError
from wizchess.mover import Mover, Step

from test_web import CFG


class Engraver(FakeMachine):
    """A fake engraver that can be connected to, told to fail, and made to take its time."""

    def __init__(self):
        super().__init__((300, 320), 1000, echo=False)
        self.head = None
        self.fail_on = None
        self.slow = False

    def connect(self):
        self.head = (0.0, 0.0)
        self.interrupted = False

    def send(self, line, timeout=None):
        if self.fail_on and self.fail_on in line:
            raise MachineError("The engraver reported an alarm.")
        return super().send(line, timeout)

    def settings(self):
        return {"32": "0", "120": "500", "121": "500"}

    def wait_until_idle(self):
        deadline = time.monotonic() + (5 if self.slow else 0)
        while time.monotonic() < deadline:
            if self.interrupted:
                raise MachineError("Stopped.")
            time.sleep(0.01)


class Sounds:
    def __init__(self):
        self.heard = []

    def play(self, name):
        self.heard.append(name)

    def then(self, name):
        self.heard.append("then " + name)

    def service(self):
        pass


@pytest.fixture
def board():
    engraver, sounds = Engraver(), Sounds()
    service = boardapi.Service(engraver, sounds, lambda: True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    threading.Thread(target=server.serve, args=(service, port, "127.0.0.1", boardapi.handle), daemon=True).start()
    threading.Thread(target=service.work, daemon=True).start()
    machine = ChipMachine("http://127.0.0.1:%d" % port, (300, 320), 1000)
    deadline = time.monotonic() + 5
    while True:
        try:
            machine.connect()
            break
        except MachineError:
            assert time.monotonic() < deadline
            time.sleep(0.02)
    machine.engraver, machine.service, machine.heard = engraver, service, sounds.heard
    return machine


def post(machine, path, body):
    request = urllib.request.Request(machine.url + path, data=body.encode())
    with urllib.request.urlopen(request, timeout=5) as r:
        return json.loads(r.read().decode())


def mover_for(machine):
    return Mover(machine, Geometry((34.5, 44.5), (265.5, 44.5), (34.5, 275.5)), 3000, 1500)


def test_a_drag_reaches_the_engraver_as_if_sent_directly(board):
    direct = FakeMachine((300, 320), 1000, echo=False)
    mover_for(direct).run(Step((4, 1), (4, 3)))
    mover_for(board).run(Step((4, 1), (4, 3)))
    assert board.engraver.lines == direct.lines
    assert board.head == direct.head == board.engraver.head


def test_nothing_is_sent_until_the_drag_is_complete(board):
    board.move_to(10, 10, 3000)
    board.magnet(True)
    assert board.engraver.lines == []
    board.wait_until_idle()
    assert len(board.engraver.lines) == 2


def test_more_actions_than_one_request_holds_are_split_between_drags(board, monkeypatch):
    from wizchess import chip

    monkeypatch.setattr(chip, "MOST_ACTIONS", 10)
    sent = []
    job = board._job
    monkeypatch.setattr(board, "_job", lambda path, body=None: sent.append(body["actions"]) or job(path, body))
    mover = mover_for(board)
    for rank in range(4):
        mover.run(Step((rank, 1), (rank, 3)), settle=False)
    board.wait_until_idle()
    assert sum(len(actions) for actions in sent) == 24 and len(sent) == 4
    assert all(actions[-1] == ["magnet", False] for actions in sent[:-1])
    assert board.engraver.lines.count("M5") == 4


def test_connect_reads_the_head_from_the_engraver(board):
    board.engraver.head = (12.5, 40.0)
    board.engraver.connect = lambda: None
    board.connect()
    assert board.head == (12.5, 40.0)


def test_an_engraver_failure_switches_the_magnet_off_and_is_reported(board):
    board.engraver.fail_on = "X100.00"
    board.move_to(50, 50, 3000)
    board.magnet(True)
    board.move_to(100, 50, 3000)
    with pytest.raises(MachineError, match="alarm"):
        board.wait_until_idle()
    assert board.engraver.lines[-1] == "M5"
    assert board.head == (50.0, 50.0)


def test_settings_are_read_and_set_through_the_board(board):
    assert board.settings()["120"] == "500"
    board.set_setting("120", 400)
    assert board.engraver.lines == ["$120=400"]


def test_stop_halts_a_running_job(board):
    board.engraver.slow = True
    board.move_to(50, 50, 3000)
    failure = []

    def drag():
        try:
            board.wait_until_idle()
        except MachineError as e:
            failure.append(str(e))

    thread = threading.Thread(target=drag)
    thread.start()
    deadline = time.monotonic() + 5
    while not board.service.running:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    board.interrupt()
    thread.join(5)
    board.stop()
    assert failure == ["Stopped."]
    assert "<stop>" in board.engraver.lines
    assert board.head is None
    assert not board.service.running


def test_requests_are_refused_with_a_reason(board):
    assert "outside the machine" in post(board, "/run", '{"actions": [["move", 500, 10, 3000]]}')["message"]
    assert "Not an action" in post(board, "/run", '{"actions": [["spin", 1]]}')["message"]
    assert "needs 'actions'" in post(board, "/run", "{}")["message"]
    assert post(board, "/run", "not json")["ok"] is False
    assert board.engraver.lines == []
    board.engraver.slow = True
    assert post(board, "/run", '{"actions": [["dwell", 0.1]]}')["ok"]
    assert "still busy" in post(board, "/run", '{"actions": [["dwell", 0.1]]}')["message"]
    assert post(board, "/stop", "")["ok"]


def test_sounds_and_the_sensor_come_from_the_board(board):
    sounds = board.sounds()
    sounds.play("capture")
    sounds.then("check")
    assert board.heard == ["capture", "then check"]
    assert board.sensor() is True


def test_an_unreachable_board_is_reported_plainly():
    machine = ChipMachine("http://127.0.0.1:9", (300, 320), 1000, timeout=0.5)
    with pytest.raises(MachineError, match="Can't reach the board's ESP32"):
        machine.connect()
    assert machine.sensor() is None
    machine.sounds().play("capture")


def test_a_whole_game_runs_on_the_laptop_with_the_board_as_a_service(board):
    app = web.App(CFG, board, sounds=board.sounds(), magnet_sensor=board.sensor)
    threading.Thread(target=app.run, daemon=True).start()
    deadline = time.monotonic() + 10

    def wait_for(condition):
        while not condition():
            assert time.monotonic() < deadline, "timed out"
            time.sleep(0.01)

    wait_for(lambda: app.question is not None)
    assert "Is the head really there?" in app.question["text"]
    app.give_answer(True)
    wait_for(lambda: app.ready and not app.busy)
    for text in ["e2 e4", "d7 d5", "e4 d5"]:
        assert app.submit(text) == (True, "")
        wait_for(lambda: app.pending is None and not app.busy)
    state = app.state()
    assert state["pieces"]["d5"] == "P" and state["parked"]["black"] == "p"
    assert state["sensor"] is True
    assert "capture" in board.heard and board.heard[0] == "start"
    assert board.engraver.lines.count("M3 S1000") == 4
