"""Optional per-user attention policy; never changes Windows notification settings."""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import time

STATES = frozenset(("permission", "question", "success", "error"))


def config_path():
    root = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return Path(root) / "openbuddy/attention.json" if root else Path.home() / ".config/openbuddy/attention.json"


def minutes(text):
    if not isinstance(text, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", text):
        raise ValueError("Invalid quiet-hours time (expected HH:MM)")
    hour, minute = map(int, text.split(":"))
    return hour * 60 + minute


class AttentionPolicy:
    def __init__(self, path=None, clock=time.monotonic, localtime=datetime.now):
        self.path = Path(path) if path is not None else config_path()
        self.clock = clock
        self.localtime = localtime
        self.next_read = 0
        self.quiet_hours = None
        self.sound_states = STATES
        self.toast_states = STATES
        self.error = None

    def refresh(self):
        if self.clock() < self.next_read:
            return
        self.next_read = self.clock() + 30
        try:
            if not self.path.exists():
                self.quiet_hours = None
                self.sound_states = self.toast_states = STATES
                self.error = None
                return
            if self.path.stat().st_size > 2048:
                raise ValueError("Attention configuration too large")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or set(data) - {"quiet_hours", "sound_states", "toast_states"}:
                raise ValueError("Invalid attention configuration")
            quiet = data.get("quiet_hours")
            if quiet is not None:
                if not isinstance(quiet, dict) or set(quiet) != {"start", "end"}:
                    raise ValueError("Invalid quiet hours")
                start, end = minutes(quiet["start"]), minutes(quiet["end"])
                if start == end:
                    raise ValueError("Quiet hours cannot span the whole day")
                quiet = (start, end)
            def choices(key):
                values = data.get(key, list(STATES))
                if (not isinstance(values, list) or len(values) > len(STATES)
                        or any(not isinstance(value, str) or value not in STATES for value in values)
                        or len(set(values)) != len(values)):
                    raise ValueError("Invalid " + key)
                return frozenset(values)
            sounds, toasts = choices("sound_states"), choices("toast_states")
            self.quiet_hours, self.sound_states, self.toast_states = quiet, sounds, toasts
            self.error = None
        except (OSError, ValueError, UnicodeError, KeyError) as error:
            self.error = type(error).__name__
            # Preserve the last valid policy; a malformed edit must not enable new alerts.

    def quiet(self):
        self.refresh()
        if self.quiet_hours is None:
            return False
        start, end = self.quiet_hours
        now = self.localtime()
        current = now.hour * 60 + now.minute
        return start <= current < end if start < end else current >= start or current < end

    def allow(self, state, channel):
        if self.quiet():
            return False
        return state in (self.sound_states if channel == "sound" else self.toast_states)
