# GRBL holds back the "ok" for spindle (magnet), dwell and motion lines until
# earlier queued moves have finished or made room, so those replies can take
# as long as the longest drag.
MOTION_TIMEOUT = 300


class MachineError(Exception):
    pass


class GcodeMachine:
    """The engraver as a small set of actions, expressed as G-code lines.

    Subclasses decide where the lines go by implementing send().
    """

    def __init__(self, travel_mm, magnet_power, homing_switches=False):
        self.travel_mm = (float(travel_mm[0]), float(travel_mm[1]))
        self.magnet_power = int(magnet_power)
        self.homing_switches = homing_switches

    def send(self, line, timeout=None):
        raise NotImplementedError

    def setup(self):
        self.send("G21")
        self.send("G90")

    def move_to(self, x, y, feed):
        if not (0 <= x <= self.travel_mm[0] and 0 <= y <= self.travel_mm[1]):
            raise ValueError(
                "(%.1f, %.1f) mm is outside the machine's %g x %g mm travel"
                % (x, y, self.travel_mm[0], self.travel_mm[1])
            )
        # G53 ignores any work offset stored on the engraver by other software.
        self.send("G53 G1 X%.2f Y%.2f F%d" % (x, y, feed), timeout=MOTION_TIMEOUT)

    def magnet(self, on):
        self.send("M3 S%d" % self.magnet_power if on else "M5", timeout=MOTION_TIMEOUT)

    def dwell(self, seconds):
        self.send("G4 P%.2f" % seconds, timeout=MOTION_TIMEOUT)

    def home(self):
        if not self.homing_switches:
            raise RuntimeError(
                "No homing switches: set homing_switches to true in config.json "
                "once they are installed and $22=1"
            )
        self.send("$H", timeout=MOTION_TIMEOUT)

    def wait_until_idle(self):
        pass

    def position(self):
        return None

    def close(self):
        pass


class FakeMachine(GcodeMachine):
    """Records and prints G-code instead of driving hardware."""

    def __init__(self, travel_mm, magnet_power, homing_switches=False, echo=True):
        super().__init__(travel_mm, magnet_power, homing_switches)
        self.lines = []
        self.echo = echo

    def send(self, line, timeout=None):
        self.lines.append(line)
        if self.echo:
            print("  > " + line)
        return []
