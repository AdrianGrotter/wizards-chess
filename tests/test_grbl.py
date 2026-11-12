from types import SimpleNamespace

import pytest

from wizchess import grbl
from wizchess.grbl import GrblError, alarm_message, find_port


def ports(monkeypatch, *items):
    monkeypatch.setattr(grbl.list_ports, "comports", lambda: [SimpleNamespace(**i) for i in items])


ENGRAVER = dict(device="/dev/cu.usbserial-9", vid=0x1A86, pid=0x7523)
OTHER = dict(device="/dev/cu.Bluetooth", vid=None, pid=None)


def test_configured_port_is_used_when_present(monkeypatch):
    ports(monkeypatch, OTHER, ENGRAVER)
    assert find_port("/dev/cu.Bluetooth") == "/dev/cu.Bluetooth"


def test_engraver_is_found_by_usb_id(monkeypatch):
    ports(monkeypatch, OTHER, ENGRAVER)
    assert find_port("auto") == "/dev/cu.usbserial-9"
    assert find_port("/dev/cu.usbserial-2140") == "/dev/cu.usbserial-9"


def test_missing_engraver_has_a_clear_message(monkeypatch):
    ports(monkeypatch, OTHER)
    with pytest.raises(GrblError, match="No engraver found on USB"):
        find_port("auto")


def test_alarm_messages():
    assert "limit switch" in alarm_message("ALARM:1")
    assert "position is lost" in alarm_message("ALARM:3")
    assert "alarm code 42" in alarm_message("ALARM:42")


BRIDGE = dict(device="/dev/cu.usbserial-2110", vid=0x10C4, pid=0xEA60)


def test_wifi_link_finds_the_esp32_bridge_not_the_engraver(monkeypatch):
    ports(monkeypatch, ENGRAVER, BRIDGE)
    assert find_port("auto", "wifi") == "/dev/cu.usbserial-2110"
    assert find_port("auto", "usb") == "/dev/cu.usbserial-9"


def test_missing_bridge_has_a_clear_message(monkeypatch):
    ports(monkeypatch, ENGRAVER)
    with pytest.raises(GrblError, match="No ESP32 WiFi bridge"):
        find_port("auto", "wifi")
