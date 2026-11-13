import array
import threading
import time

from wizchess import voice, web
from wizchess.machine import FakeMachine

from test_web import CFG


def block(peak):
    return array.array("h", [peak, -peak] * 240).tobytes()


def test_segmenter_hands_back_a_sentence_after_a_pause():
    segmenter = voice.Segmenter(level=700, quiet_blocks=5, shortest=3, lead=2)
    for _ in range(10):
        assert segmenter.feed(block(50)) is None
    for _ in range(8):
        assert segmenter.feed(block(5000)) is None
    results = [segmenter.feed(block(50)) for _ in range(5)]
    assert results[:4] == [None] * 4
    assert len(results[4]) == (2 + 8 + 5) * 960


def test_segmenter_drops_a_click():
    segmenter = voice.Segmenter(level=700, quiet_blocks=5, shortest=3)
    segmenter.feed(block(5000))
    assert [segmenter.feed(block(50)) for _ in range(5)] == [None] * 5
    assert segmenter.blocks == []


def test_segmenter_ignores_a_steady_noisy_room():
    segmenter = voice.Segmenter(level=700)
    for peak in range(100, 1500, 20):
        assert segmenter.feed(block(peak)) is None
    assert segmenter.blocks == []


class Local:
    """The web app without the network in between."""

    url = "test"

    def __init__(self, app):
        self.app = app

    def state(self):
        return self.app.state()

    def command(self, line):
        return self.app.submit(line)

    def answer(self, yes):
        self.app.give_answer(yes)

    def stop(self):
        self.app.stop()


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def talking():
    app = web.App(CFG, FakeMachine((300, 320), 1000, echo=False))
    threading.Thread(target=app.run, daemon=True).start()
    said = []
    return app, voice.Conversation(Local(app), said.append), said


def settle(app, conversation):
    wait_for(lambda: app.pending is None and not app.busy)
    conversation.watch()


def test_a_game_by_voice_from_a_question_to_checkmate():
    app, conversation, said = talking()
    settle(app, conversation)
    assert app.submit("outline") == (True, "")
    wait_for(lambda: app.question is not None)
    conversation.watch()
    assert "Say yes for" in said[-1]
    assert conversation.heard("knight to f3") == "ignored"
    assert conversation.heard("No.") == "answer"
    settle(app, conversation)

    for sentence in ["pawn to f3", "e5", "pawn to g4"]:
        assert conversation.heard(sentence).startswith("sent")
        conversation.watch()
        settle(app, conversation)
    assert conversation.heard("Queen to h4.") == "sent 'd8 h4'"
    conversation.watch()
    settle(app, conversation)
    assert said[-2:] == ["Queen to H4.", "Checkmate: Black wins."]
    assert app.state()["pieces"]["h4"] == "q"


def test_the_page_switches_the_microphone_and_shows_what_was_heard():
    app = web.App(CFG, FakeMachine((300, 320), 1000, echo=False))
    threading.Thread(target=app.run, daemon=True).start()
    wait_for(lambda: app.pending is None and not app.busy)
    assert app.state()["voice"] is None
    listener = voice.Listener(voice.OwnBoard(app), "no-such-model.bin", aloud=False)
    app.voice = listener
    assert app.state()["voice"] == {"on": False, "status": "Off", "heard": [], "said": ""}

    listener.hear("Knight to f3.")
    listener.hear("what a lovely day")
    wait_for(lambda: app.pending is None and not app.busy)
    shown = app.state()["voice"]
    assert [(h["text"], h["did"]) for h in shown["heard"]] == [
        ("Knight to f3.", "sent 'g1 f3'"), ("what a lovely day", "ignored"),
    ]
    assert shown["said"] == "Knight to F3."
    assert app.state()["pieces"]["f3"] == "N"

    listener.switch(True)
    wait_for(lambda: not listener.on)
    assert "speech model no-such-model.bin is missing" in listener.status


def test_chatter_and_refusals_are_handled_aloud():
    app, conversation, said = talking()
    settle(app, conversation)
    del said[:]
    assert conversation.heard("so anyway, where were we") == "ignored"
    assert said == []
    assert conversation.heard("e2 e5") == "sent 'e2 e5'"
    wait_for(lambda: app.state()["log"][-1]["error"])
    settle(app, conversation)
    assert len(said) == 2 and "E5" in said[1].upper()
    assert app.state()["pieces"]["e2"] == "P"
