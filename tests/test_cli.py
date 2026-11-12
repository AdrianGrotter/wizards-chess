from wizchess import cli
from wizchess.machine import FakeMachine


def run_with(monkeypatch, command):
    machines = []

    def make_machine(cfg, fake):
        machine = FakeMachine(cfg["travel_mm"], cfg["magnet_power"], echo=False)
        machines.append(machine)
        return machine

    monkeypatch.setattr(cli, "make_machine", make_machine)
    monkeypatch.setitem(cli.COMMANDS, "grid", command)
    return cli.main(["--fake", "grid"]), machines[0]


def test_ctrl_c_during_a_move_stops_the_engraver(monkeypatch, capsys):
    def interrupted(cfg, machine, args):
        raise KeyboardInterrupt

    code, machine = run_with(monkeypatch, interrupted)
    assert code == 1
    assert machine.lines[-1] == "<stop>"
    assert machine.head is None
    assert "push it back into its corner" in capsys.readouterr().out


def test_engraver_errors_end_the_run_with_a_message(monkeypatch, capsys):
    def failing(cfg, machine, args):
        raise cli.MachineError("Lost the USB connection to the engraver.")

    code, _ = run_with(monkeypatch, failing)
    assert code == 1
    assert "Lost the USB connection" in capsys.readouterr().out


def test_ctrl_d_at_a_prompt_quits():
    def eof(prompt):
        raise EOFError

    original = cli.input if hasattr(cli, "input") else None
    cli.input = eof
    try:
        assert cli.ask("> ") == "quit"
    finally:
        if original is None:
            del cli.input
        else:
            cli.input = original


def test_outline_circles_the_corners_until_quit(monkeypatch):
    answers = iter(["", "", "", "", "quit"])
    monkeypatch.setattr(cli, "ask", lambda prompt: next(answers))
    machine = FakeMachine((300, 320), 1000, echo=False)
    cfg = {"board": {"a1": [31, 41], "h1": [269, 41], "a8": [31, 279]}, "travel_feed": 3000, "drag_feed": 1500}
    cli.cmd_outline(cfg, machine, None)
    corners = [line for line in machine.lines if line.endswith("F3000")][:5]
    assert corners == [
        "G53 G1 X31.00 Y41.00 F3000",
        "G53 G1 X31.00 Y279.00 F3000",
        "G53 G1 X269.00 Y279.00 F3000",
        "G53 G1 X269.00 Y41.00 F3000",
        "G53 G1 X31.00 Y41.00 F3000",
    ]
    assert machine.lines[-1] == "G53 G1 X0.00 Y0.00 F3000"


class Presses:
    """Stands in for the Enter queue: answers waits from a script, and reports
    a press 'during' the leg that ends at the given move count."""

    def __init__(self, waits, press_after_moves):
        self.waits = list(waits)
        self.press_after_moves = dict(press_after_moves)
        self.machine = None

    def _moves(self):
        return sum(1 for line in self.machine.lines if line.endswith("F3000") and "G53" in line)

    def empty(self):
        return self._moves() not in self.press_after_moves

    def get(self):
        moves = self._moves()
        if moves in self.press_after_moves:
            return self.press_after_moves.pop(moves)
        return self.waits.pop(0)


def test_cycle_pulls_round_the_corners_and_pauses_on_enter():
    from wizchess.geometry import Geometry
    from wizchess.mover import Mover

    machine = FakeMachine((300, 320), 1000, echo=False)
    machine.head = None
    mover = Mover(machine, Geometry((31, 41), (269, 41), (31, 279)), 6000, 6000)
    said = []
    # Start, Enter during the 5th leg (pause at A8), Enter to carry on, 'quit' during the 7th leg.
    presses = Presses(waits=["", ""], press_after_moves={5: "", 7: "quit"})
    presses.machine = machine
    cli.cycle_corners(machine, mover, 3000, presses, said.append)
    drags = [line for line in machine.lines if line.endswith("F3000")]
    assert drags == [
        "G53 G1 X31.00 Y279.00 F3000",
        "G53 G1 X269.00 Y279.00 F3000",
        "G53 G1 X269.00 Y41.00 F3000",
        "G53 G1 X31.00 Y41.00 F3000",
        "G53 G1 X31.00 Y279.00 F3000",
        "G53 G1 X269.00 Y279.00 F3000",
        "G53 G1 X269.00 Y41.00 F3000",
    ]
    assert any("Paused at A8" in s for s in said)
    assert machine.lines.index("M3 S1000") < machine.lines.index(drags[0])
    assert machine.lines[-2] == "M5"
