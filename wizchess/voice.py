"""Play by talking to the board: a microphone on the laptop, speech recognised offline.

The laptop listens all the time, has whisper.cpp write down what was said,
turns chess talk into commands for the board's web page (see heard.py), and
answers aloud. The board itself can be the ESP32 or `wizchess web`.
"""
import array
import atexit
import io
import json
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

from .heard import Interpreter

RATE = 16000
BLOCK = 480  # samples: 30 ms
VOCABULARY = (
    "A game of chess, moves spoken aloud. Squares: a1, b2, c3, d4, e5, f6, g7, h8. "
    "Pieces: pawn, knight, bishop, rook, queen, king. Takes, castle kingside, castle queenside."
)


class Board:
    """The board's web page, as a program sees it."""

    def __init__(self, url, timeout=5):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _call(self, path, body=None):
        data = None if body is None else body.encode()
        with urllib.request.urlopen(urllib.request.Request(self.url + path, data=data), timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def state(self):
        return self._call("/state")

    def command(self, line):
        reply = self._call("/command", line)
        return reply["ok"], reply["message"]

    def answer(self, yes):
        self._call("/answer", "yes" if yes else "no")

    def stop(self):
        self._call("/stop", "")


class Segmenter:
    """Cuts the microphone's stream into sentences, by loudness.

    Feed it one block at a time; it hands back a whole sentence once the
    speaker has been quiet for a moment. level is the loudness (0 to 32767)
    a block needs to count as speech; the room's own noise raises it.
    """

    def __init__(self, level=700, quiet_blocks=20, shortest=6, longest=330, lead=10):
        self.level = level
        self.quiet_blocks = quiet_blocks
        self.shortest = shortest
        self.longest = longest
        self.lead = lead
        self.noise = 0.0
        self.reset()

    def reset(self):
        self.before = []
        self.blocks = []
        self.loud = 0
        self.quiet = 0

    def feed(self, block):
        samples = array.array("h", block)
        peak = max(max(samples), -min(samples)) if samples else 0
        speech = peak > max(self.level, self.noise * 3)
        if not self.blocks:
            if not speech:
                self.noise += (peak - self.noise) * 0.05
                self.before = (self.before + [block])[-self.lead:]
                return None
            self.blocks = self.before + [block]
            self.loud, self.quiet = 1, 0
            return None
        self.blocks.append(block)
        if speech:
            self.loud += 1
            self.quiet = 0
        else:
            self.quiet += 1
        if self.quiet < self.quiet_blocks and len(self.blocks) < self.longest:
            return None
        sentence = b"".join(self.blocks) if self.loud >= self.shortest else None
        self.reset()
        return sentence


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Recogniser:
    """whisper.cpp's server, kept running so the model is loaded once."""

    def __init__(self, model, program="whisper-server"):
        if shutil.which(program) is None:
            raise ValueError("%s was not found. Run this inside `nix develop`." % program)
        self.port = _free_port()
        self.process = subprocess.Popen(
            [program, "-m", model, "--host", "127.0.0.1", "--port", str(self.port), "-l", "en", "-nt",
             "--prompt", VOCABULARY],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 60
        while True:
            if self.process.poll() is not None:
                raise ValueError("The speech recogniser stopped at once. Is %s a whisper.cpp model?" % model)
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                if time.monotonic() > deadline:
                    self.close()
                    raise ValueError("The speech recogniser did not start within a minute.")
                time.sleep(0.2)

    def write_down(self, sentence):
        """The words in a sentence of 16 kHz, 16-bit mono sound."""
        sound = io.BytesIO()
        with wave.open(sound, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(sentence)
        boundary = "wizchessvoiceboundary"
        parts = b""
        for name, value in (("response_format", "json"), ("temperature", "0.0")):
            parts += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, name, value)).encode()
        parts += (
            '--%s\r\nContent-Disposition: form-data; name="file"; filename="said.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n" % boundary
        ).encode() + sound.getvalue() + ("\r\n--%s--\r\n" % boundary).encode()
        request = urllib.request.Request(
            "http://127.0.0.1:%d/inference" % self.port, data=parts,
            headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        )
        with urllib.request.urlopen(request, timeout=30) as r:
            return json.loads(r.read().decode()).get("text", "").strip()

    def close(self):
        self.process.terminate()


class Voice:
    """Prints the replies to the players and, when asked to, says them aloud with the laptop's own voice."""

    def __init__(self, aloud=False):
        self.program = shutil.which("say") if aloud else None
        self.speaking = False
        self.lock = threading.Lock()

    def say(self, text):
        print("board: %s" % text)
        if self.program is None:
            return
        with self.lock:
            self.speaking = True
            try:
                subprocess.run([self.program, text])
                time.sleep(0.3)
            finally:
                self.speaking = False


class Conversation:
    """Carries what was said to the board, and tells the players what the board has to say."""

    def __init__(self, board, say):
        self.board = board
        self.say = say
        self.interpreter = Interpreter()
        self.question = None
        self.last_log = None
        self.status = None

    def heard(self, text):
        """Act on one written-down sentence. Returns what was done, for the terminal."""
        result = self.interpreter.hear(text, self.board.state())
        if result is None:
            return "ignored"
        if result.kind == "stop":
            self.board.stop()
            self.say(result.spoken)
        elif result.kind == "answer":
            self.board.answer(result.value)
        elif result.kind == "say":
            self.say(result.spoken)
        else:
            accepted, message = self.board.command(result.value)
            self.say(result.spoken if accepted else message)
            return "sent '%s'" % result.value if accepted else "refused"
        return result.kind

    def watch(self):
        """Look at the board once and say aloud what is new: questions, problems, check and the end."""
        state = self.board.state()
        log = state["log"]
        newest = log[-1]["n"] if log else 0
        if self.last_log is None:
            self.last_log = newest
            self.status = state["status"]
        for entry in log:
            if entry["n"] > self.last_log and entry["error"]:
                self.say(entry["text"].split("\n")[0])
        self.last_log = max(self.last_log, newest)

        question = state["question"]
        if question and question != self.question:
            self.say("%s Say yes for %s, or no for %s." % (question["text"], question["yes"], question["no"]))
        self.question = question

        status = state["status"]
        if not state["busy"] and status != self.status:
            if status.endswith("in check"):
                self.say("Check.")
            elif status.startswith(("Checkmate", "Game over")):
                self.say(status + ".")
            self.status = status


class OwnBoard:
    """A game running in this same program, for a Conversation to talk to."""

    url = "this program"

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


class Listener:
    """The microphone, switched on and off while the program runs.

    state() is what the web page shows: whether it is on, what it is doing,
    and the last sentences it heard with what became of each.
    """

    SHOWN = 6

    def __init__(self, board, model, level=700, microphone=None, aloud=False):
        self.model = model
        self.level = level
        self.microphone = microphone
        self.voice = Voice(aloud)
        self.conversation = Conversation(board, self._say)
        self.on = False
        self.status = "Off"
        self.heard = []
        self.count = 0
        self.said = ""
        self.thread = None
        self.recogniser = None
        atexit.register(self._close)

    def _say(self, text):
        self.said = text
        self.voice.say(text)

    def state(self):
        return {"on": self.on, "status": self.status, "heard": self.heard, "said": self.said}

    def switch(self, on):
        if on and not self.on:
            self.on = True
            self.status = "Starting..."
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        elif not on:
            self.on = False
            self.status = "Off"

    def hear(self, text):
        """Act on one written-down sentence and remember it for the page."""
        try:
            did = self.conversation.heard(text)
        except (OSError, ValueError):
            did = "no answer from the board"
        self.count += 1
        self.heard = (self.heard + [{"n": self.count, "text": text, "did": did}])[-self.SHOWN:]
        print("heard: %s -> %s" % (text, did))

    def _watch(self):
        while self.on:
            try:
                self.conversation.watch()
            except (OSError, ValueError):
                pass
            time.sleep(0.7)

    def _close(self):
        if self.recogniser is not None:
            self.recogniser.close()
            self.recogniser = None

    def _run(self):
        try:
            if not os.path.exists(self.model):
                raise ValueError(
                    "The speech model %s is missing. 'Playing by voice' in the manual says how to get it."
                    % self.model
                )
            try:
                import sounddevice
            except ImportError:
                raise ValueError("The microphone needs the sounddevice package. Run this inside `nix develop`.")
            if self.recogniser is None:
                self.status = "Loading the speech recogniser..."
                self.recogniser = Recogniser(self.model)
            blocks = queue.Queue()
            segmenter = Segmenter(self.level)
            try:
                stream = sounddevice.RawInputStream(
                    samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16", device=self.microphone,
                    callback=lambda data, frames, when, status: blocks.put(bytes(data)),
                )
            except Exception as e:
                raise ValueError("The microphone could not be opened: %s" % e)
            with stream:
                self.status = "Listening. Say a move, like: knight to f3."
                threading.Thread(target=self._watch, daemon=True).start()
                while self.on:
                    try:
                        block = blocks.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    if self.voice.speaking:
                        segmenter.reset()
                        continue
                    sentence = segmenter.feed(block)
                    if sentence is None:
                        continue
                    text = self.recogniser.write_down(sentence)
                    if text and self.on:
                        self.hear(text)
            self.status = "Off"
        except (ValueError, OSError) as e:
            self.status = str(e)
        finally:
            self.on = False


def _watching(conversation, pause=0.7):
    reachable = True
    while True:
        try:
            conversation.watch()
            reachable = True
        except (OSError, ValueError):
            if reachable:
                print("No answer from the board at %s. Still trying." % conversation.board.url)
            reachable = False
        time.sleep(pause)


def _act(conversation, text):
    try:
        print("heard: %s -> %s" % (text, conversation.heard(text)))
    except (OSError, ValueError):
        print("heard: %s -> no answer from the board at %s" % (text, conversation.board.url))


def run(url, model, typed=False, aloud=False, level=700, microphone=None):
    """Listen and talk until Ctrl-C. With typed, sentences come from the keyboard instead."""
    board = Board(url)
    try:
        board.state()
    except (OSError, ValueError):
        raise ValueError(
            "No board answers at %s. Start it first (python -m wizchess web), or give its "
            "address with --board." % url
        )
    if typed:
        conversation = Conversation(board, Voice(aloud).say)
        threading.Thread(target=_watching, args=(conversation,), daemon=True).start()
        print("Type what you would say, like: knight to f3. Ctrl-D ends.")
        while True:
            try:
                _act(conversation, input("> "))
            except EOFError:
                return

    # An ordinary kill must still shut the recogniser down with this program.
    signal.signal(signal.SIGTERM, lambda number, frame: sys.exit(0))
    listener = Listener(board, model, level, microphone, aloud)
    listener.switch(True)
    shown = None
    while listener.on:
        if listener.status != shown:
            shown = listener.status
            print(shown)
        time.sleep(0.2)
    raise ValueError(listener.status)
