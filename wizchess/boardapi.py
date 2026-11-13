"""The board as a service: other devices tell it what to do, over HTTP.

The game itself (rules, routes, the web page, voice) runs elsewhere and
sends plain requests: move the head, switch the magnet, play a sound. What
keeps the hardware safe stays here: every request is checked against the
machine's reach before anything moves, a failure switches the magnet off,
and a stop always gets through.

Requests that use the engraver are jobs. One runs at a time; the request
that starts it returns the job's number at once, and GET /status shows the
number of the last job that finished, with its error or result.

Runs under both Python (for tests) and MicroPython (on the ESP32).
"""
import _thread
import json
import time

from . import web
from .sound import Silent

MOST_ACTIONS = 600
LONGEST_DWELL = 10

ABOUT = {
    "GET /status": "head, busy, job, done, error, result, connected, sensor, travel_mm",
    "POST /connect": "job: connect to the engraver afresh and read where the head is",
    "POST /run": 'job: {"actions": [["move", x_mm, y_mm, feed_mm_per_min], ["magnet", true], ["dwell", seconds]]}',
    "POST /stop": "halt the engraver at once and switch the magnet off",
    "POST /settings": "job: the engraver's settings, as the job's result",
    "POST /set": 'job: {"name": "120", "value": "500"} changes one engraver setting',
    "POST /unlock": "job: clear an engraver alarm",
    "POST /home": "job: run homing, if the board has homing switches",
    "POST /sound": '{"name": "capture"} plays a sound now; with "queued": true, after the ones before it',
}


class Service:
    """Carries out jobs one at a time on the thread that calls work()."""

    def __init__(self, machine, sounds=None, magnet_sensor=None):
        self.machine = machine
        self.sounds = sounds or Silent()
        self.magnet_sensor = magnet_sensor
        self.lock = _thread.allocate_lock()
        self.sound_lock = _thread.allocate_lock()
        self.pending = None
        self.job = 0
        self.done = 0
        self.running = False
        self.stopping = False
        self.connected = False
        self.error = None
        self.result = None

    def check(self, actions):
        """ValueError unless actions is a list this board can carry out."""
        if not isinstance(actions, list) or not actions:
            raise ValueError("actions must be a list with at least one action.")
        if len(actions) > MOST_ACTIONS:
            raise ValueError("Too many actions in one request: %d, at most %d." % (len(actions), MOST_ACTIONS))
        for action in actions:
            kind = action[0] if isinstance(action, list) and action else None
            numbers = action[1:] if kind else []
            if kind == "magnet" and len(action) == 2 and isinstance(action[1], bool):
                continue
            if not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in numbers):
                raise ValueError("Not an action: %r" % (action,))
            if kind == "move" and len(action) == 4 and action[3] > 0:
                self.machine.check_reach(action[1], action[2])
            elif kind == "dwell" and len(action) == 2 and 0 <= action[1] <= LONGEST_DWELL:
                pass
            else:
                raise ValueError("Not an action: %r" % (action,))

    def submit(self, kind, argument=None):
        """Queue a job. Returns (accepted, message, job number)."""
        with self.lock:
            if self.running or self.pending is not None:
                return False, "The board is still busy with the last request.", None
            self.job += 1
            self.pending = (self.job, kind, argument)
            return True, "", self.job

    def stop(self):
        """Halt whatever the engraver is doing. Called from the server's thread."""
        with self.lock:
            if self.pending is not None:
                self.done, self.pending = self.pending[0], None
                self.error, self.result = "Stopped.", None
                return True, ""
        if not self.running:
            return False, "Nothing is moving."
        self.stopping = True
        self.machine.interrupt()
        return True, ""

    def play(self, name, queued=False):
        with self.sound_lock:
            if queued:
                self.sounds.then(name)
            else:
                self.sounds.play(name)

    def status(self):
        head = self.machine.head
        return {
            "connected": self.connected,
            "head": None if head is None else [head[0], head[1]],
            "busy": self.running or self.pending is not None,
            "job": self.job,
            "done": self.done,
            "error": self.error,
            "result": self.result,
            "sensor": None if self.magnet_sensor is None else bool(self.magnet_sensor()),
            "travel_mm": [self.machine.travel_mm[0], self.machine.travel_mm[1]],
        }

    def _carry_out(self, kind, argument):
        machine = self.machine
        if kind == "connect":
            self.connected = False
            machine.connect()
            self.connected = True
            return None
        if not self.connected:
            raise ValueError("The board is not connected to the engraver. Send POST /connect first.")
        if kind == "run":
            for action in argument:
                if action[0] == "move":
                    machine.move_to(action[1], action[2], int(action[3]))
                elif action[0] == "magnet":
                    machine.magnet(action[1])
                else:
                    machine.dwell(action[1])
            machine.wait_until_idle()
        elif kind == "settings":
            return machine.settings()
        elif kind == "set":
            machine.set_setting(argument[0], argument[1])
        elif kind == "unlock":
            machine.unlock()
        elif kind == "home":
            machine.home()
        return None

    def _do(self, job, kind, argument):
        error = result = None
        try:
            result = self._carry_out(kind, argument)
        except Exception as e:
            error = str(e) or repr(e)
            if self.stopping:
                error = "Stopped."
                try:
                    self.machine.stop()
                except Exception:
                    pass
            elif kind == "run":
                try:
                    self.machine.magnet(False)
                except Exception:
                    pass
            if getattr(self.machine, "out_of_step", False):
                self.connected = False
        self.error, self.result = error, result
        self.stopping = False
        self.done = job
        self.running = False

    def work(self):
        """Carry out queued jobs forever."""
        while True:
            with self.lock:
                pending, self.pending = self.pending, None
                if pending is not None:
                    self.running = True
            if pending is None:
                try:
                    self.machine.idle()
                    with self.sound_lock:
                        self.sounds.service()
                except Exception:
                    pass
                time.sleep(0.05)
            else:
                self._do(*pending)


def handle(conn, service):
    request = web._read_request(conn)
    if request is None:
        return
    method, path, body = request
    if method == "GET" and path == "/":
        web._respond(conn, ABOUT)
        return
    if method == "GET" and path == "/status":
        web._respond(conn, service.status())
        return
    if method != "POST":
        web._respond(conn, {"ok": False, "message": "No such request. GET / lists them."}, status="404 Not Found")
        return
    try:
        data = json.loads(body) if body.strip() else {}
        if not isinstance(data, dict):
            raise ValueError("The request's body must be a JSON object.")
        if path == "/stop":
            accepted, message = service.stop()
            reply = {"ok": accepted, "message": message}
        elif path == "/sound":
            service.play(str(data["name"]), bool(data.get("queued", False)))
            reply = {"ok": True, "message": ""}
        else:
            argument = None
            if path == "/run":
                argument = data["actions"]
                service.check(argument)
            elif path == "/set":
                argument = (str(data["name"]), str(data["value"]))
            elif path not in ("/connect", "/settings", "/unlock", "/home"):
                web._respond(
                    conn, {"ok": False, "message": "No such request. GET / lists them."}, status="404 Not Found"
                )
                return
            accepted, message, job = service.submit(path[1:], argument)
            reply = {"ok": accepted, "message": message, "job": job}
    except KeyError as e:
        reply = {"ok": False, "message": "The request needs '%s'." % e.args[0]}
    except ValueError as e:
        reply = {"ok": False, "message": str(e)}
    web._respond(conn, reply)


def run(machine, port, host="0.0.0.0", sounds=None, magnet_sensor=None):
    """Serve requests until the program is ended."""
    service = Service(machine, sounds, magnet_sensor)
    _thread.start_new_thread(web.serve, (service, port, host, handle))
    service.submit("connect")
    service.work()
