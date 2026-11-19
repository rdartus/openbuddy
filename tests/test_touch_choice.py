"""Simulated FT3168, prompt assembly and gesture safety (never touches a board)."""

from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "device"))
from buddy_prompt import Prompt
from buddy_protocol import encode, validate_command
from test_amoled import load_module


class PromptTests(unittest.TestCase):
    def test_fragmented_title_options_and_one_shot_answer(self):
        prompt = Prompt()
        prompt.begin({"kind": "permission", "token": "per_1", "text": "A" * 90,
                      "count": 3, "parts": 2}, "permission")
        prompt.option({"token": "per_1", "index": 0, "text": "REFUSE"})
        prompt.option({"token": "per_1", "index": 1, "text": "ONCE"})
        self.assertIsNone(prompt.ready())
        prompt.part({"token": "per_1", "index": 1, "text": "ALWAYS: *.py"})
        prompt.option({"token": "per_1", "index": 2, "text": "ALWAYS"})
        self.assertEqual(prompt.ready()["text"], "A" * 90 + "ALWAYS: *.py")
        prompt.move(1)
        self.assertEqual(prompt.ready()["selected"], 1)
        self.assertEqual(prompt.choose(), {"event": "choice", "kind": "permission",
                                           "token": "per_1", "index": 1})
        self.assertIsNone(prompt.choose())
        prompt.clear()
        self.assertIsNone(prompt.ready())

    def test_bounded_frames_and_untrusted_indexes(self):
        for command, fields in (("prompt", dict(kind="permission", count=3, parts=6, text="x" * 90)),
                                ("part", dict(index=5, text="x" * 120)),
                                ("option", dict(index=7, text="x" * 120))):
            message = dict(v=1, id=2147483647, cmd=command, token="a" * 48, **fields)
            self.assertEqual(validate_command(message), command)
            self.assertLessEqual(len(encode(message)), 257)
        prompt = Prompt()
        prompt.begin({"kind": "form", "token": "f", "text": "Title", "count": 2, "parts": 1}, "question")
        with self.assertRaises(ValueError):
            prompt.part({"token": "other", "index": 1, "text": "oops"})
        with self.assertRaises(ValueError):
            prompt.option({"token": "f", "index": 2, "text": "oops"})


class TouchTests(unittest.TestCase):
    def setUp(self):
        self.point = None
        self.bus = Mock()

        def read(address, register, target):
            self.assertEqual(address, 0x38)
            if register == 2:
                target[:] = bytes((0 if self.point is None else 1,))
            else:
                x, y = self.point
                target[:] = bytes(((x >> 8) & 15, x & 255, (y >> 8) & 15, y & 255))

        self.bus.readfrom_mem_into.side_effect = read
        cfg = types.SimpleNamespace(TOUCH_ADDRESS=0x38)
        clock = types.SimpleNamespace(ticks_diff=lambda a, b: a - b, ticks_add=lambda a, b: a + b)
        self.module = load_module("ft3168", {"board_config": cfg, "time": clock})
        self.touch = self.module.Touch(lambda: self.bus)

    def test_vendor_registers_and_inverse_landscape_rotation(self):
        self.bus.writeto_mem.assert_called_once_with(0x38, 0, b"\x00")
        self.point = (10, 20)
        self.assertEqual(self.touch.sample("landscape"), (435, 10))
        self.assertEqual(self.touch.sample("landscape_inv"), (20, 269))
        self.point = (300, 20)
        self.assertIsNone(self.touch.sample("landscape"))
        self.touch.close()
        self.bus.deinit.assert_not_called()  # The IMU owns the shared bus.

    def test_swipes_taps_and_rotation_cancel(self):
        self.point = (80, 320)  # Logical (135, 80).
        self.assertIsNone(self.touch.poll(0, "landscape"))
        self.point = (80, 390)  # Swipe left in the logical canvas.
        self.assertIsNone(self.touch.poll(60, "landscape"))
        self.point = None
        self.assertEqual(self.touch.poll(120, "landscape"), "left")
        self.point = (80, 320)
        self.touch.poll(180, "landscape")
        self.point = None
        self.assertEqual(self.touch.poll(240, "landscape"), "tap")
        self.point = (80, 320)
        self.touch.poll(300, "landscape")
        self.point = None
        self.assertIsNone(self.touch.poll(360, "landscape_inv"))

    def test_bus_errors_cancel_a_gesture_and_trigger_reinitialization(self):
        self.point = (80, 320)
        self.touch.poll(0, "landscape")
        self.bus.readfrom_mem_into.side_effect = OSError("I2C unavailable")
        self.assertIsNone(self.touch.poll(60, "landscape"))
        self.assertIsNone(self.touch.poll(120, "landscape"))
        with self.assertRaises(OSError):
            self.touch.poll(180, "landscape")
        self.assertIsNone(self.touch.start)

    def test_inverted_landscape_preserves_logical_swipe_direction(self):
        self.point = (80, 320)
        self.touch.poll(0, "landscape_inv")
        self.point = (80, 390)
        self.touch.poll(60, "landscape_inv")
        self.point = None
        self.assertEqual(self.touch.poll(120, "landscape_inv"), "right")


if __name__ == "__main__":
    unittest.main()
