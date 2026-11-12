"""WiFi bridge between the laptop and the engraver.

The laptop talks G-code to the ESP32's USB serial port exactly as it would
to the engraver's own USB port; this carries it over WiFi.
"""
import select
import sys
import time

from wizchess.wifi import Engraver

# GRBL's real-time commands act on their own, without a newline.
REALTIME = b"?!~\x18"


def relay(engraver):
    usb_in = sys.stdin.buffer
    usb_out = sys.stdout.buffer
    poller = select.poll()
    poller.register(usb_in, select.POLLIN)
    poller.register(engraver.ws, select.POLLIN)
    line = b""
    while True:
        for ready in poller.poll(1000):
            if ready[0] is engraver.ws:
                output = engraver.read_output()
                if output:
                    usb_out.write(output)
                continue
            byte = usb_in.read(1)
            if not byte:
                continue
            if byte in REALTIME:
                engraver.command(byte.decode())
            elif byte == b"\n":
                text = line.strip().decode()
                line = b""
                if text:
                    engraver.command(text)
            elif byte != b"\r":
                line += byte


def run(config, say):
    while True:
        engraver = None
        try:
            engraver = Engraver(
                config["engraver_host"], config.get("http_port", 80), config.get("websocket_port", 81)
            )
            say("connected to engraver %s" % config["engraver_host"])
            relay(engraver)
        except Exception as e:
            say("connection lost (%s), retrying" % e)
            time.sleep(2)
        finally:
            if engraver is not None:
                engraver.close()
