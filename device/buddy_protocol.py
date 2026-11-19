"""Small, versioned JSON-line protocol shared by MicroPython and CPython."""

import json

VERSION = 1
FIRMWARE_VERSION = "0.6.3"
DEVICE_NAME = "OpenBuddy"
SERVICE_UUID = "c8ad0001-4f90-4ab8-9976-22401b7861b0"
RX_UUID = "c8ad0002-4f90-4ab8-9976-22401b7861b0"
TX_UUID = "c8ad0003-4f90-4ab8-9976-22401b7861b0"
MAX_FRAME = 256
CHUNK_SIZE = 20  # Works even with the default ATT MTU of 23.
HEARTBEAT_MS = 15_000
STATES = ("standby", "idle", "thinking", "working", "permission", "question",
          "success", "error", "retry")


def encode(message):
    data = json.dumps(message).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise ValueError("Frame exceeds 256 bytes")
    return data + b"\n"


def fit_status(message):
    """Keep the touch capability in a bounded status ACK before optional diagnostics."""
    try:
        encode(message)
        return message
    except ValueError:
        message.pop("state", None)
    try:
        encode(message)
        return message
    except ValueError:
        message.pop("pet", None)  # Omit an oversized identifier, never truncate it.
    encode(message)
    return message


def validate_command(message):
    if message.get("v") != VERSION:
        raise ValueError("Unsupported protocol version")
    request_id = message.get("id")
    if type(request_id) is not int or not 0 <= request_id <= 2_147_483_647:
        raise ValueError("Invalid request id")
    command = message.get("cmd")
    if command not in ("ping", "status", "state", "hid_arm", "prompt", "part", "option"):
        raise ValueError("Unknown command")
    if command == "state":
        if message.get("state") not in STATES:
            raise ValueError("Unknown state")
        label = message.get("label", "")
        if not isinstance(label, str) or len(label) > 24:
            raise ValueError("Label must contain at most 24 characters")
        info = message.get("info", "")
        if not isinstance(info, str) or len(info) > 24:
            raise ValueError("Info must contain at most 24 characters")
    if command in ("prompt", "part", "option"):
        token = message.get("token")
        if not isinstance(token, str) or not 1 <= len(token) <= 48 or not all(
                "a" <= character <= "z" or "A" <= character <= "Z"
                or "0" <= character <= "9" or character in "_-" for character in token):
            raise ValueError("Invalid request token")
        if command == "prompt":
            if message.get("kind") not in ("form", "permission"):
                raise ValueError("Invalid prompt kind")
            if type(message.get("count")) is not int or not 2 <= message["count"] <= 8:
                raise ValueError("Invalid option count")
            if type(message.get("parts")) is not int or not 1 <= message["parts"] <= 6:
                raise ValueError("Invalid prompt length")
            position, total = message.get("position", 1), message.get("total", 1)
            if (type(position) is not int or type(total) is not int
                    or not 1 <= position <= total <= 100):
                raise ValueError("Invalid request position")
            text = message.get("text")
            if not isinstance(text, str) or not 1 <= len(text) <= 90:
                raise ValueError("Invalid prompt text")
        else:
            if type(message.get("index")) is not int or not 0 <= message["index"] < (6 if command == "part" else 8):
                raise ValueError("Invalid option index")
            text = message.get("text")
            if not isinstance(text, str) or not 1 <= len(text) <= 120:
                raise ValueError("Invalid option text")
        if any(not 32 <= ord(character) <= 126 for character in text):
            raise ValueError("Prompt text must be printable ASCII")
    return command


class Decoder:
    """Reassemble ATT chunks, with bounded memory and newline resynchronization."""

    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False
        self.errors = 0

    def feed(self, chunk):
        messages = []
        for value in chunk:
            if value == 10:
                if self.buffer and not self.dropping:
                    try:
                        message = json.loads(self.buffer.decode("utf-8"))
                        if not isinstance(message, dict):
                            raise ValueError("Expected an object")
                        messages.append(message)
                    except (ValueError, UnicodeError):
                        self.errors += 1
                self.buffer = bytearray()
                self.dropping = False
            elif not self.dropping:
                if len(self.buffer) >= MAX_FRAME:
                    self.buffer = bytearray()
                    self.dropping = True
                    self.errors += 1
                else:
                    self.buffer.append(value)
        return messages
