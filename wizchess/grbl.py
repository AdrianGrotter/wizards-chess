import time

import serial
from serial.tools import list_ports

from .machine import MOTION_TIMEOUT, GcodeMachine, MachineError

# USB vendor and product ids of the serial chips the engraver can be reached through:
# the WCH CH340 on the MKS DLC32 board itself, or the Silicon Labs CP2102N on the
# ESP32 DevKitC running the WiFi bridge (esp32/main.py).
USB_IDS = {
    "usb": {(0x1A86, 0x7523)},
    "wifi": {(0x10C4, 0xEA60)},
}

ALARMS = {
    "1": "a limit switch was hit",
    "2": "a move would have left the work area",
    "3": "the engraver was reset while moving, so its position is lost",
    "8": "homing could not find its switch",
    "9": "homing could not find its switch",
}


class GrblError(MachineError):
    pass


def alarm_message(text):
    code = text.partition(":")[2].strip()
    reason = ALARMS.get(code, "alarm code %s" % code)
    return (
        "The engraver stopped with an alarm: %s. Type 'unlock' to continue, "
        "or quit and push the head back into its corner." % reason
    )


def find_port(configured, link="usb"):
    """The serial device to talk G-code on: the configured one if present, else found by USB id.

    link "usb" is the engraver's own USB port; "wifi" is the ESP32 bridge.
    """
    ports = list(list_ports.comports())
    if configured and configured != "auto" and any(p.device == configured for p in ports):
        return configured
    for port in ports:
        if (port.vid, port.pid) in USB_IDS[link]:
            return port.device
    if link == "wifi":
        raise GrblError("No ESP32 WiFi bridge found on USB. Is it plugged in (UART port)?")
    raise GrblError("No engraver found on USB. Is it plugged in and switched on?")


class GrblMachine(GcodeMachine):
    """Drives a GRBL engraver over a USB serial port."""

    def __init__(
        self, port, baud, travel_mm, magnet_power, homing_switches=False, timeout=10.0, link="usb"
    ):
        super().__init__(travel_mm, magnet_power, homing_switches)
        self.timeout = timeout
        self.out_of_step = False
        self.link = link
        self.serial = serial.Serial()
        self.serial.port = find_port(port, link)
        self.serial.baudrate = baud
        self.serial.timeout = 0.1
        self.serial.dtr = False
        self.serial.rts = False
        try:
            self.serial.open()
        except serial.SerialException as e:
            raise GrblError(
                "Can't open %s (%s). Close LightBurn, LaserGRBL or any other program using the engraver."
                % (self.serial.port, e)
            )
        # Over WiFi the ESP32 restarts when its port opens and must rejoin the
        # network and the engraver before anything answers.
        self._wait_until_ready(seconds=40 if link == "wifi" else 15)
        self.setup()
        self.head = self.position()

    def _write(self, data):
        try:
            self.serial.write(data)
        except serial.SerialException:
            self.out_of_step = True
            raise GrblError("Lost the USB connection to the engraver.")

    def _readline(self):
        try:
            return self.serial.readline()
        except serial.SerialException:
            self.out_of_step = True
            raise GrblError("Lost the USB connection to the engraver.")

    def _drain(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._readline()
        self.serial.reset_input_buffer()

    def _wait_until_ready(self, seconds=15):
        """Wait out the restart the ESP32 board does when the port opens."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.serial.reset_input_buffer()
            self._write(b"?")
            reply_deadline = time.monotonic() + 0.5
            while time.monotonic() < reply_deadline:
                if self._readline().startswith(b"<"):
                    self._drain(1.0)
                    return
        if self.link == "wifi":
            raise GrblError(
                "The engraver did not answer through the ESP32 bridge on %s. Check that the "
                "ESP32 can join the WiFi and reach the engraver (esp32/config.json)." % self.serial.port
            )
        raise GrblError("The engraver did not answer on %s." % self.serial.port)

    def _read_line(self, deadline, waiting_for):
        while True:
            raw = self._readline()
            if raw:
                text = raw.decode(errors="replace").strip()
                if text:
                    return text
            elif time.monotonic() > deadline:
                # A reply may still arrive later and would be taken as the
                # answer to the next command, so stop trusting the connection.
                self.out_of_step = True
                raise GrblError(
                    "No reply from the engraver to %r. Quit and start the tool again." % waiting_for
                )

    def send(self, line, timeout=None):
        """Send one line and return the lines GRBL printed before 'ok'."""
        if self.out_of_step:
            raise GrblError(
                "The connection to the engraver is out of step after an earlier error. "
                "Quit and start the tool again."
            )
        self._write((line + "\n").encode())
        deadline = time.monotonic() + (timeout or self.timeout)
        replies = []
        while True:
            text = self._read_line(deadline, line)
            if text == "ok":
                return replies
            if text.startswith("error"):
                raise GrblError("The engraver rejected %r (%s)." % (line, text))
            if text.startswith("ALARM"):
                self._drain(0.5)
                raise GrblError(alarm_message(text))
            replies.append(text)

    def status(self):
        if self.out_of_step:
            raise GrblError("The connection to the engraver is out of step. Quit and start the tool again.")
        self._write(b"?")
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
        deadline = time.monotonic() + MOTION_TIMEOUT
        while True:
            state = self.status()
            if state.startswith("<Idle"):
                return
            if state.startswith("<Alarm"):
                raise GrblError(
                    "The engraver is in an alarm state. Type 'unlock' to continue, "
                    "or quit and push the head back into its corner."
                )
            if state.startswith(("<Hold", "<Door")):
                raise GrblError("The engraver is paused (%s). Quit and start the tool again." % state)
            if time.monotonic() > deadline:
                raise GrblError("The engraver did not finish moving within %d seconds." % MOTION_TIMEOUT)
            time.sleep(0.1)

    def stop(self):
        """Halt all motion at once, including queued moves. A reset also switches the magnet off."""
        self.head = None
        try:
            self._write(b"!")
            time.sleep(0.3)
            self._write(b"\x18")
            self._wait_until_ready(seconds=5)
            self.out_of_step = False
        except GrblError:
            pass

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
            self.out_of_step = False
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
