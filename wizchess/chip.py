"""Drives the board through the ESP32's service (see boardapi.py), from a laptop.

The game here plans a drag as usual; its moves, magnet switches and pauses
are collected and sent to the ESP32 as one request, which carries them out.
"""
import json
import time
import urllib.error
import urllib.request

from .machine import MOTION_TIMEOUT, GcodeMachine, MachineError

# The ESP32 takes at most this many actions in one request.
MOST_ACTIONS = 600


class ChipMachine(GcodeMachine):
    # The engraver keeps counting the head's position between sessions.
    keeps_position = True

    def __init__(self, url, travel_mm, magnet_power, homing_switches=False, timeout=5.0):
        super().__init__(travel_mm, magnet_power, homing_switches)
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.head = None
        self.actions = []
        self._seen = None
        self._seen_at = 0.0
        self._silent_until = 0.0

    def _call(self, path, body=None, timeout=None):
        data = None if body is None else json.dumps(body).encode()
        try:
            request = urllib.request.Request(self.url + path, data=data)
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode())
        except (OSError, ValueError) as e:
            raise MachineError(
                "Can't reach the board's ESP32 at %s (%s). Is it switched on, and is this "
                "computer on its network?" % (self.url, e)
            )

    def _status(self, timeout=None):
        self._seen = self._call("/status", timeout=timeout)
        self._seen_at = time.monotonic()
        return self._seen

    def _take_head(self, status):
        head = status["head"]
        self.head = None if head is None else (float(head[0]), float(head[1]))

    def _job(self, path, body=None):
        """Start a job on the ESP32 and wait for it. Returns the status that reports it finished."""
        reply = self._call(path, {} if body is None else body)
        if not reply["ok"]:
            raise MachineError(reply["message"])
        deadline = time.monotonic() + MOTION_TIMEOUT
        while True:
            if self.interrupted:
                raise MachineError("Stopped.")
            status = self._status()
            if status["done"] >= reply["job"]:
                break
            if time.monotonic() > deadline:
                raise MachineError("The board did not finish within %d seconds." % MOTION_TIMEOUT)
            time.sleep(0.1)
        if status["error"]:
            self._take_head(status)
            raise MachineError(status["error"])
        return status

    def connect(self):
        """Have the ESP32 connect to the engraver afresh and read where the head is."""
        self.actions = []
        self.interrupted = False
        self._take_head(self._job("/connect"))

    def send(self, line, timeout=None):
        raise MachineError("The board's ESP32 takes actions, not G-code lines.")

    def setup(self):
        pass

    def move_to(self, x, y, feed):
        try:
            self.check_reach(x, y)
        except ValueError:
            self.actions = []
            raise
        self.actions.append(["move", round(x, 3), round(y, 3), int(feed)])
        self.head = (float(x), float(y))

    def magnet(self, on):
        self.actions.append(["magnet", bool(on)])

    def dwell(self, seconds):
        self.actions.append(["dwell", seconds])

    def flush(self):
        """Send the collected actions and wait until the board has carried them out."""
        while self.actions:
            count = len(self.actions)
            if count > MOST_ACTIONS:
                # Cut where the magnet is off, so no piece is left waiting mid-drag.
                count = MOST_ACTIONS
                while count > 1 and self.actions[count - 1] != ["magnet", False]:
                    count -= 1
                if count == 1:
                    count = MOST_ACTIONS
            actions, self.actions = self.actions[:count], self.actions[count:]
            try:
                self._job("/run", {"actions": actions})
            except MachineError:
                self.actions = []
                raise

    def wait_until_idle(self):
        self.flush()

    def idle(self):
        self.flush()

    def settings(self):
        self.flush()
        return self._job("/settings")["result"] or {}

    def set_setting(self, key, value):
        self.flush()
        self._job("/set", {"name": str(key), "value": str(value)})

    def unlock(self):
        self.actions = []
        self._job("/unlock")

    def home(self):
        if not self.homing_switches:
            raise MachineError(
                "No homing switches: set homing_switches to true in config.json "
                "once they are installed and $22=1"
            )
        self.actions = []
        self._take_head(self._job("/home"))

    def position(self):
        self.flush()
        self._take_head(self._status())
        return self.head

    def stop(self):
        """Halt all motion at once. The head's position is whatever the ESP32 still knows of it."""
        self.actions = []
        self.interrupted = False
        self.head = None
        try:
            self._call("/stop", {})
            deadline = time.monotonic() + 15
            status = self._status()
            while status["busy"] and time.monotonic() < deadline:
                time.sleep(0.1)
                status = self._status()
            if not status["busy"]:
                self._take_head(status)
        except MachineError:
            pass

    def sensor(self):
        """Whether the board's sensor feels a magnet; None without a sensor or without an answer.

        The web page asks this with every refresh, so an ESP32 that doesn't
        answer is left alone for a few seconds instead of holding the page up.
        """
        now = time.monotonic()
        if now < self._silent_until:
            return None
        if self._seen is None or now - self._seen_at > 0.5:
            try:
                self._status(timeout=1.0)
            except MachineError:
                self._silent_until = time.monotonic() + 5
                return None
        return self._seen["sensor"]

    def sounds(self):
        return ChipSounds(self)


class ChipSounds:
    """Plays the game's sounds on the board's own speaker."""

    def __init__(self, machine):
        self.machine = machine

    def _play(self, name, queued):
        try:
            self.machine._call("/sound", {"name": name, "queued": queued})
        except MachineError:
            pass

    def play(self, name):
        self._play(name, False)

    def then(self, name):
        self._play(name, True)

    def service(self):
        pass
