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
