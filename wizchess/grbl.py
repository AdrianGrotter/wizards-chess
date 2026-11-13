import serial
from serial.tools import list_ports

from .protocol import GrblError, GrblProtocol, alarm_message  # noqa: F401

# USB vendor and product id of the engraver's serial chip, the WCH CH340 on the MKS DLC32 board.
USB_IDS = {(0x1A86, 0x7523)}


def find_port(configured):
    """The engraver's serial device: the configured one if present, else found by USB id."""
    ports = list(list_ports.comports())
    if configured and configured != "auto" and any(p.device == configured for p in ports):
        return configured
    for port in ports:
        if (port.vid, port.pid) in USB_IDS:
            return port.device
    raise GrblError("No engraver found on USB. Is it plugged in and switched on?")


class GrblMachine(GrblProtocol):
    """Drives a GRBL engraver over a USB serial port."""

    def __init__(self, port, baud, travel_mm, magnet_power, homing_switches=False, timeout=10.0):
        super().__init__(travel_mm, magnet_power, homing_switches, timeout)
        self.serial = serial.Serial()
        self.serial.port = find_port(port)
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
        self.silent_message = "The engraver did not answer on %s." % self.serial.port
        # The board behind the port restarts when it opens.
        self._wait_until_ready(seconds=15)
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
