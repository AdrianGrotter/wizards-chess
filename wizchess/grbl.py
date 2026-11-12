import time

import serial

from .machine import MOTION_TIMEOUT, GcodeMachine, MachineError


class GrblError(MachineError):
    pass


class GrblMachine(GcodeMachine):
    """Drives a GRBL engraver over a USB serial port."""

    def __init__(self, port, baud, travel_mm, magnet_power, homing_switches=False, timeout=10.0):
        super().__init__(travel_mm, magnet_power, homing_switches)
        self.timeout = timeout
        self.serial = serial.Serial()
        self.serial.port = port
        self.serial.baudrate = baud
        self.serial.timeout = 0.1
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.open()
        self._wait_until_ready()
        self.setup()

    def _wait_until_ready(self, seconds=15):
        """Wait out the restart the ESP32 board may do when the port opens."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.serial.reset_input_buffer()
            self.serial.write(b"?")
            reply_deadline = time.monotonic() + 0.5
            while time.monotonic() < reply_deadline:
                if self.serial.readline().startswith(b"<"):
                    time.sleep(1.0)
                    self.serial.reset_input_buffer()
                    return
        raise GrblError("The engraver did not answer on %s" % self.serial.port)

    def _read_line(self, deadline, waiting_for):
        while True:
            raw = self.serial.readline()
            if raw:
                text = raw.decode(errors="replace").strip()
                if text:
                    return text
            elif time.monotonic() > deadline:
                raise GrblError("No reply from the engraver to %r" % waiting_for)

    def send(self, line, timeout=None):
        """Send one line and return the lines GRBL printed before 'ok'."""
        self.serial.write((line + "\n").encode())
        deadline = time.monotonic() + (timeout or self.timeout)
        replies = []
        while True:
            text = self._read_line(deadline, line)
            if text == "ok":
                return replies
            if text.startswith("error") or text.startswith("ALARM"):
                raise GrblError("%r -> %s" % (line, text))
            replies.append(text)

    def status(self):
        self.serial.write(b"?")
        deadline = time.monotonic() + self.timeout
        while True:
            text = self._read_line(deadline, "?")
            if text.startswith("<"):
                return text

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
        while not self.status().startswith("<Idle"):
            time.sleep(0.1)

    def info(self):
        replies = self.send("$I")
        # The MKS firmware follows $I with a second block (WiFi status) and its own "ok".
        deadline = time.monotonic() + 1.0
        try:
            while True:
                text = self._read_line(deadline, "$I")
                if text == "ok":
                    break
                replies.append(text)
        except GrblError:
            pass
        return replies

    def settings(self):
        result = {}
        for line in self.send("$$"):
            if line.startswith("$") and "=" in line:
                key, value = line[1:].split("=", 1)
                result[key] = value
        return result

    def close(self):
        self.serial.close()
