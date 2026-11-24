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

    def test_request_navigation_is_one_shot_never_an_approval(self):
        prompt = Prompt()
        prompt.begin({"kind": "permission", "token": "p1", "text": "Full scope", "count": 2,
                      "parts": 1, "position": 1, "total": 2}, "permission")
        prompt.option({"token": "p1", "index": 0, "text": "REFUSE"})
        prompt.option({"token": "p1", "index": 1, "text": "ONCE"})
        self.assertEqual(prompt.navigate(1), {"event": "navigate", "kind": "permission", "token": "p1", "step": 1})
        self.assertEqual(prompt.ready()["selected"], 0)
        self.assertIsNone(prompt.navigate(0))
        prompt.choose()
        self.assertIsNone(prompt.navigate(1))
        with self.assertRaises(ValueError):
            validate_command(dict(v=1, id=1, cmd="prompt", kind="permission", count=2,
                                  parts=1, text="Scope", token="p1", position=3, total=2))
        self.assertLessEqual(len(encode(dict(v=1, id=2147483647, cmd="prompt", token="a" * 48,
                                             kind="permission", count=8, parts=6, text="x" * 60,
                                             position=100, total=100))), 257)


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
        cfg = types.SimpleNamespace(TOUCH_ADDRESS=0x38,
                                    UI_CHOICE_HOLD_RECT=(224, 202, 232, 32))
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

    def test_swipes_never_validate_and_rotation_cancels(self):
        self.point = (80, 320)  # Logical (135, 80).
        self.assertIsNone(self.touch.poll(0, "landscape"))
        self.point = (80, 390)  # Swipe left in the logical canvas.
        self.assertIsNone(self.touch.poll(60, "landscape"))
        self.point = None
        self.assertEqual(self.touch.poll(120, "landscape"), "left")
        self.point = (80, 320)
        self.touch.poll(180, "landscape")
        self.point = None
        self.assertIsNone(self.touch.poll(240, "landscape"))
        self.point = (80, 320)
        self.touch.poll(300, "landscape")
        self.point = None
        self.assertIsNone(self.touch.poll(360, "landscape_inv"))

    def test_only_a_one_second_stationary_hold_inside_choice_can_answer(self):
        request = object()
        self.point = (210, 195)  # Logical (260, 210), inside the choice outline.
        self.assertIsNone(self.touch.poll(0, "landscape", request))
        for now in (180, 360, 540, 720, 900):
            self.assertIsNone(self.touch.poll(now, "landscape", request))
        self.point = None
        self.assertEqual(self.touch.poll(1080, "landscape", request), "hold")
        self.point = (210, 195)
        self.touch.poll(1200, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(1500, "landscape", request))  # Short press.
        self.point = (110, 195)  # Logical (260, 110), question instead of choice.
        self.touch.poll(3000, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(4080, "landscape", request))

    def test_swipe_then_phantom_hold_or_movement_back_never_answers(self):
        request = object()
        self.point = (210, 195)  # Logical (260, 210).
        self.touch.poll(0, "landscape", request)
        self.point = (210, 285)  # Logical (170, 210), swipe left.
        self.touch.poll(60, "landscape", request)
        self.point = None
        self.assertEqual(self.touch.poll(120, "landscape", request), "left")
        self.point = (210, 195)
        self.touch.poll(180, "landscape", request)
        for now in (360, 540, 720, 900, 1080):
            self.touch.poll(now, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(1260, "landscape", request))  # Began during the guard.
        self.point = (210, 195)
        self.touch.poll(3000, "landscape", request)
        self.point = (210, 145)  # Move 50 pixels and return to the start.
        self.touch.poll(3060, "landscape", request)
        self.point = (210, 195)
        self.touch.poll(3120, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(4080, "landscape", request))

    def test_hold_is_cancelled_when_the_pending_request_changes(self):
        original, replacement = object(), object()
        self.point = (210, 195)
        self.touch.poll(0, "landscape", original)
        self.point = None
        self.assertIsNone(self.touch.poll(1080, "landscape", replacement))
        self.point = (210, 195)
        self.touch.poll(2500, "landscape_inv", replacement)
        self.point = None
        self.assertIsNone(self.touch.poll(3600, "landscape", replacement))

    def test_inverted_landscape_hold_uses_same_visible_choice_area(self):
        request = object()
        self.point = (69, 260)  # Logical (260, 210) after rotation.
        self.touch.poll(0, "landscape_inv", request)
        for now in (180, 360, 540, 720, 900):
            self.touch.poll(now, "landscape_inv", request)
        self.point = None
        self.assertEqual(self.touch.poll(1080, "landscape_inv", request), "hold")

    def test_missing_touch_samples_or_leaving_choice_zone_cannot_validate(self):
        request = object()
        self.point = (210, 195)
        self.touch.poll(0, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(1080, "landscape", request))
        self.point = (210, 195)
        self.touch.poll(2500, "landscape", request)
        for now in (2680, 2860, 3040, 3220, 3400):
            self.touch.poll(now, "landscape", request)
        self.point = (180, 195)  # 30 pixels outside the outlined choice vertically.
        self.touch.poll(3460, "landscape", request)
        self.point = (210, 195)
        self.touch.poll(3520, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(3580, "landscape", request))
        self.point = (210, 195)
        self.touch.poll(5000, "landscape", request)
        self.touch.poll(5060, "landscape", request)
        self.touch.poll(5600, "landscape", request)  # A missed half-second invalidates the hold.
        self.touch.poll(5780, "landscape", request)
        self.touch.poll(5960, "landscape", request)
        self.point = None
        self.assertIsNone(self.touch.poll(6080, "landscape", request))

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

    def test_vertical_swipes_select_requests_not_answers(self):
        self.point = (80, 320)  # Logical (135, 80).
        self.touch.poll(0, "landscape")
        self.point = (150, 320)  # Logical (135, 150).
        self.touch.poll(60, "landscape")
        self.point = None
        self.assertEqual(self.touch.poll(120, "landscape"), "down")


if __name__ == "__main__":
    unittest.main()
