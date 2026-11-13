"""Starts the chess board's software on the ESP32, under MicroPython.

config.json holds the WiFi details and the mode. In "game" mode the whole
game runs here and is played from a web page the ESP32 serves; game.json is
the project's config.json with the board's measurements. In "bridge" mode
the ESP32 only carries G-code between the laptop's USB cable and the
engraver.
"""
import json
import sys
import time

import network

HOSTNAME = "wizardchess"


def say(text):
    sys.stdout.write("[board] %s\r\n" % text)


def load(name):
    with open(name) as f:
        return json.load(f)


def connect_wifi(ssid, password, seconds=20):
    try:
        network.hostname(HOSTNAME)
    except Exception:
        pass
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
        deadline = time.ticks_add(time.ticks_ms(), seconds * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                raise OSError("could not join WiFi %r" % ssid)
            time.sleep_ms(100)
    return wlan.ifconfig()[0]


def open_access_point(ssid, password):
    """The ESP32's own WiFi network, for when the shared one keeps its devices apart."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ssid, password=password, authmode=network.AUTH_WPA2_PSK)
    return ap.ifconfig()[0]


def play(config, ip):
    import _thread

    from wizchess import web
    from wizchess.wifi import WifiMachine

    game = load("game.json")
    machine = WifiMachine(
        config["engraver_host"], game["travel_mm"], game["magnet_power"], game.get("homing_switches", False),
        config.get("http_port", 80), config.get("websocket_port", 81),
    )
    _thread.stack_size(24 * 1024)
    say("Play at http://%s/ (or http://%s.local/)" % (ip, HOSTNAME))
    if config.get("ap_ssid"):
        ap_ip = open_access_point(config["ap_ssid"], config["ap_password"])
        say("Or join the WiFi network %s and play at http://%s/" % (config["ap_ssid"], ap_ip))
    sounds = None
    if game.get("sound"):
        from dfplayer import Player

        wiring = game["sound"]
        sounds = Player(wiring["tx"], wiring["rx"], wiring["busy"], wiring.get("volume", 20))
    web.run(game, machine, 80, state_path="state.json", sounds=sounds)


def main():
    config = load("config.json")
    while True:
        try:
            ip = connect_wifi(config["wifi_ssid"], config["wifi_password"])
            break
        except OSError as e:
            say("%s, retrying" % e)
            time.sleep(2)
    say("WiFi %s, address %s" % (config["wifi_ssid"], ip))
    if config.get("mode", "game") == "bridge":
        import bridge

        bridge.run(config, say)
    else:
        play(config, ip)


main()
