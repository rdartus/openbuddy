"""Run with the MicroPython 1.29 Unix port, never with CPython mocks."""

import board_config
import buddy_orientation
import buddy_protocol as protocol
from buddy_usb import BuddyUSB, Console as UsbConsole
from buddy_prompt import Prompt
import companion
import ft3168
import pet_format
import pet_player
import sdcard_spi
import storage


message = {"v": protocol.VERSION, "id": 12, "cmd": "state", "state": "idle"}
assert protocol.validate_command(message) == "state"
decoder = protocol.Decoder()
frame = protocol.encode(message)
assert decoder.feed(frame[:5]) == []
assert decoder.feed(frame[5:]) == [message]
assert decoder.feed(b"\xff\n") == []
assert decoder.errors == 1

prompt = Prompt()
prompt.begin({"kind": "form", "token": "form1", "text": "Choose", "parts": 1,
              "count": 2}, "question")
assert prompt.ready() is None
prompt.option({"token": "form1", "index": 0, "text": "No"})
prompt.option({"token": "form1", "index": 1, "text": "Yes"})
assert prompt.ready()["selected"] == 0
prompt.move(1)
assert prompt.choose() == {"event": "choice", "kind": "form", "token": "form1", "index": 1}
assert prompt.choose() is None


class Console:
    def __init__(self):
        self.frames = []

    def write(self, data):
        self.frames.append(data)


console = Console()
# Exercise MicroPython's actual stdio and select objects, not a CPython mock.
raw_console = UsbConsole()
raw_console.write(b"")
assert raw_console.read() == b""
usb = BuddyUSB(console=console)
usb._command({"v": 1, "id": 13, "cmd": "state", "state": "question"}, 100)
assert usb.state == "question"
assert decoder.feed(console.frames[-1])[0]["event"] == "ack"
usb._command({"v": 1, "id": 14, "cmd": "prompt", "kind": "form", "token": "form1",
              "text": "Choose", "parts": 1, "count": 2}, 120)
usb._command({"v": 1, "id": 15, "cmd": "option", "token": "form1",
              "index": 0, "text": "No"}, 140)
usb._command({"v": 1, "id": 16, "cmd": "option", "token": "form1",
              "index": 1, "text": "Yes"}, 160)
usb.prompt.move(1)
usb.choose()
assert decoder.feed(console.frames[-1]) == [
    {"v": 1, "event": "choice", "kind": "form", "token": "form1", "index": 1}]
assert usb.online(160)
print("MicroPython 1.29 runtime smoke: imports, protocol, USB and prompt OK")
