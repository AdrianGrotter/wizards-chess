import time

from .machine import MOTION_TIMEOUT, GcodeMachine, MachineError

ALARMS = {
    "1": "a limit switch was hit",
    "2": "a move would have left the work area",
    "3": "the engraver was reset while moving, so its position is lost",
    "8": "homing could not find its switch",
    "9": "homing could not find its switch",
}

if hasattr(time, "ticks_ms"):
    # MicroPython has no time.monotonic, and its millisecond counter wraps around.
    _last_ticks = time.ticks_ms()
    _elapsed_ms = 0

    def monotonic():
        global _last_ticks, _elapsed_ms
        now = time.ticks_ms()
        _elapsed_ms += time.ticks_diff(now, _last_ticks)
        _last_ticks = now
        return _elapsed_ms / 1000
else:
    monotonic = time.monotonic


class GrblError(MachineError):
    pass


def alarm_message(text):
    code = text.partition(":")[2].strip()
    reason = ALARMS.get(code, "alarm code %s" % code)
    return (
        "The engraver stopped with an alarm: %s. Type 'unlock' to continue, "
        "or quit and push the head back into its corner." % reason
    )


class GrblProtocol(GcodeMachine):
    """Talks GRBL: sends lines, waits for each 'ok', reads status reports.

    Subclasses carry the bytes: _write(data) sends them, _readline() returns
    the next line of engraver output (or b"" after a short wait with none),
    and _reset_input() throws away output that has already arrived.
    """

    restart_hint = "Quit and start the tool again."
    # How many bytes of commands may be on their way without an 'ok' yet. 0
    # waits for every 'ok' before sending the next line. A link whose replies
    # arrive late sets this, kept under the size of the engraver's input buffer.
    window = 0
    silent_message = "The engraver did not answer."

    def __init__(self, travel_mm, magnet_power, homing_switches=False, timeout=10.0):
        super().__init__(travel_mm, magnet_power, homing_switches)
        self.timeout = timeout
        self.out_of_step = False
        self.unanswered = []

    def _write(self, data):
        raise NotImplementedError

    def _readline(self):
        raise NotImplementedError

    def _reset_input(self):
        pass

    def _drain(self, seconds):
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            self._readline()
        self._reset_input()

    def _wait_until_ready(self, seconds=15):
        """Wait until the engraver answers a status request, then drop whatever else it printed."""
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            self._reset_input()
            self._write(b"?")
            reply_deadline = monotonic() + 0.5
            while monotonic() < reply_deadline:
                if self._readline().startswith(b"<"):
                    self._drain(1.0)
                    return
        raise GrblError(self.silent_message)

    def _read_line(self, deadline, waiting_for):
        while True:
            if self.interrupted:
                self.out_of_step = True
                raise GrblError("Stopped.")
            raw = self._readline()
            if raw:
                try:
                    text = raw.decode().strip()
                except UnicodeError:
                    continue
                if text:
                    return text
            elif monotonic() > deadline:
                # A reply may still arrive later and would be taken as the
                # answer to the next command, so stop trusting the connection.
                self.out_of_step = True
                raise GrblError(
                    "No reply from the engraver to %r. %s" % (waiting_for, self.restart_hint)
                )

    def _answer(self, text):
        """Take one line of engraver output as the answer to the oldest unanswered command, if it is one."""
        if text == "ok":
            if self.unanswered:
                self.unanswered.pop(0)
            return True
        if text.startswith("error"):
            line = self.unanswered.pop(0) if self.unanswered else "a command"
            raise GrblError("The engraver rejected %r (%s)." % (line, text))
        if text.startswith("ALARM"):
            self.unanswered = []
            self._drain(0.5)
            raise GrblError(alarm_message(text))
        return False

    def _settle(self, count, timeout):
        """Wait until at most count commands are still unanswered."""
        deadline = monotonic() + timeout
        while len(self.unanswered) > count:
            self._answer(self._read_line(deadline, self.unanswered[0]))

    def flush(self):
        """Wait for the 'ok' of every command sent so far."""
        self._settle(0, MOTION_TIMEOUT)

    def send(self, line, timeout=None):
        """Send one line. Returns the lines GRBL printed before its 'ok'.

        With a window, plain G-code is sent without waiting for its 'ok' and
        nothing is returned; flush() or wait_until_idle() collects the answers.
        """
        if self.out_of_step:
            raise GrblError(
                "The connection to the engraver is out of step after an earlier error. "
                + self.restart_hint
            )
        if self.window and not line.startswith("$"):
            while self.unanswered and sum(len(l) + 1 for l in self.unanswered) + len(line) + 1 > self.window:
                self._settle(len(self.unanswered) - 1, timeout or MOTION_TIMEOUT)
            self._write((line + "\n").encode())
            self.unanswered.append(line)
            return []
        self.flush()
        self._write((line + "\n").encode())
        self.unanswered.append(line)
        deadline = monotonic() + (timeout or self.timeout)
        replies = []
        while self.unanswered:
            text = self._read_line(deadline, line)
            if not self._answer(text):
                replies.append(text)
        return replies

    def status(self):
        if self.out_of_step:
            raise GrblError("The connection to the engraver is out of step. " + self.restart_hint)
        self._write(b"?")
        deadline = monotonic() + self.timeout
        while True:
            text = self._read_line(deadline, "?")
            if text.startswith("<"):
                return text
            self._answer(text)

    def position(self):
        """Head position in machine coordinates."""
        fields = {}
        for field in self.status().strip("<>").split("|"):
            name, _, value = field.partition(":")
            if name in ("MPos", "WPos", "WCO"):
                fields[name] = [float(v) for v in value.split(",")]
        if "MPos" in fields:
            return tuple(fields["MPos"][:2])
        if "WPos" in fields and "WCO" in fields:
            return tuple(w + o for w, o in zip(fields["WPos"][:2], fields["WCO"][:2]))
        return None

    def wait_until_idle(self):
        # G4 only replies once every queued move has finished.
        self.send("G4 P0", timeout=MOTION_TIMEOUT)
        self.flush()
        deadline = monotonic() + MOTION_TIMEOUT
        while True:
            state = self.status()
            if state.startswith("<Idle"):
                return
            if state.startswith("<Alarm"):
                raise GrblError(
                    "The engraver is in an alarm state. Type 'unlock' to continue, "
                    "or quit and push the head back into its corner."
                )
            if state.startswith("<Hold") or state.startswith("<Door"):
                raise GrblError("The engraver is paused (%s). %s" % (state, self.restart_hint))
            if monotonic() > deadline:
                raise GrblError("The engraver did not finish moving within %d seconds." % MOTION_TIMEOUT)
            time.sleep(0.1)

    def _came_to_rest(self, seconds):
        """Whether the engraver reports, within seconds, that it has stopped moving."""
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            self._write(b"?")
            reply_deadline = monotonic() + 0.3
            while monotonic() < reply_deadline:
                line = self._readline()
                if line.startswith(b"<Hold:0") or line.startswith(b"<Idle"):
                    return True
                if line.startswith(b"<"):
                    break
        return False

    def _end_pause(self):
        """Reset the engraver if it was left paused, dropping the paused moves. Returns whether it was.

        A paused engraver takes commands in but answers none of them.
        """
        self._write(b"?")
        deadline = monotonic() + 1.0
        line = b""
        while monotonic() < deadline and not line.startswith(b"<"):
            line = self._readline()
        if not line.startswith(b"<Hold"):
            return False
        self._came_to_rest(3.0)
        self._write(b"\x18")
        self._wait_until_ready(seconds=5)
        return True

    def stop(self):
        """Halt all motion at once, including queued moves. The reset also switches the magnet off.

        The head's position stays known only if the engraver came to rest
        before the reset; a reset in mid-motion loses steps.
        """
        self.head = None
        self.interrupted = False
        self.unanswered = []
        try:
            self._reset_input()
            self._write(b"!")
            at_rest = self._came_to_rest(3.0)
            self._write(b"\x18")
            self._wait_until_ready(seconds=5)
            self.out_of_step = False
            if at_rest:
                self.head = self.position()
        except GrblError:
            pass

    def info(self):
        replies = self.send("$I")
        # The MKS firmware follows $I with a second block (WiFi status) and its own "ok".
        deadline = monotonic() + 1.0
        try:
            while True:
                text = self._read_line(deadline, "$I")
                if text == "ok":
                    break
                replies.append(text)
        except GrblError:
            self.out_of_step = False
        return replies

    def settings(self):
        result = {}
        for line in self.send("$$"):
            if line.startswith("$") and "=" in line:
                key, value = line[1:].split("=", 1)
                result[key] = value
        return result
