"""Attention-policy tests never send desktop notifications or play sounds."""

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from pc.attention import AttentionPolicy
from pc.notifications import SoundNotifier
from pc.toasts import DesktopNotifier


class AttentionTests(unittest.TestCase):
    def test_midnight_and_unchanged_state_do_not_notify_after_quiet_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attention.json"
            path.write_text(json.dumps({"quiet_hours": {"start": "22:00", "end": "08:00"},
                                        "sound_states": ["permission"], "toast_states": []}), encoding="utf-8")
            now = [datetime(2026, 11, 19, 23, 30)]
            tick = [0]
            policy = AttentionPolicy(path, clock=lambda: tick[0], localtime=lambda: now[0])
            sounds, toasts = [], []
            sound = SoundNotifier(player=sounds.append)
            toast = DesktopNotifier(poster=lambda *value: toasts.append(value))
            self.assertFalse(policy.allow("permission", "sound"))
            sound.observe("permission", notify=policy.allow("permission", "sound"))
            now[0] = datetime(2026, 11, 20, 7, 59)
            self.assertFalse(policy.allow("permission", "sound"))
            now[0] = datetime(2026, 11, 20, 8, 0)
            self.assertTrue(policy.allow("permission", "sound"))
            sound.observe("permission", notify=policy.allow("permission", "sound"))
            toast.observe("permission", notify=policy.allow("permission", "toast"))
            self.assertEqual((sounds, toasts), ([], []))
            sound.observe("question", notify=policy.allow("question", "sound"))
            sound.observe("permission", notify=policy.allow("permission", "sound"))
            self.assertEqual(sounds, ["SystemExclamation"])

    def test_invalid_reload_keeps_last_valid_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attention.json"
            path.write_text('{"sound_states": []}', encoding="utf-8")
            tick = [0]
            policy = AttentionPolicy(path, clock=lambda: tick[0])
            self.assertFalse(policy.allow("permission", "sound"))
            path.write_text('{"sound_states": ["unknown"]}', encoding="utf-8")
            tick[0] = 31
            self.assertFalse(policy.allow("permission", "sound"))
            self.assertEqual(policy.error, "ValueError")
