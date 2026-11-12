import serial
from serial.tools import list_ports

from .protocol import GrblError, GrblProtocol, alarm_message  # noqa: F401

# USB vendor and product ids of the serial chips the engraver can be reached through:
# the WCH CH340 on the MKS DLC32 board itself, or the Silicon Labs CP2102N on the
# ESP32 DevKitC running the WiFi bridge (esp32/bridge.py).
USB_IDS = {
    "usb": {(0x1A86, 0x7523)},
    "wifi": {(0x10C4, 0xEA60)},
}


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


class GrblMachine(GrblProtocol):
    """Drives a GRBL engraver over a USB serial port."""

    def __init__(
        self, port, baud, travel_mm, magnet_power, homing_switches=False, timeout=10.0, link="usb"
    ):
        super().__init__(travel_mm, magnet_power, homing_switches, timeout)
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
        if link == "wifi":
            self.silent_message = (
                "The engraver did not answer through the ESP32 bridge on %s. Check that the ESP32 "
                "is in bridge mode and can reach the engraver (esp32/config.json)." % self.serial.port
            )
        else:
            self.silent_message = "The engraver did not answer on %s." % self.serial.port
        # The board behind the port restarts when it opens; over WiFi the ESP32
        # must also rejoin the network and the engraver before anything answers.
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

    def _reset_input(self):
        self.serial.reset_input_buffer()

    def close(self):
        self.serial.close()
