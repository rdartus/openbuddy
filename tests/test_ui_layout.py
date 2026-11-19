"""Check both profile layouts without a board, display driver or pet assets."""

import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


FIRMWARE = Path(__file__).resolve().parents[1] / "device"


def load(name):
    spec = importlib.util.spec_from_file_location("_ui_test_" + name, FIRMWARE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BoundedDisplay:
    def __init__(self, width, height):
        self.w, self.h = width, height
        self.calls = []
        self.texts = []

    def fill_rect(self, x, y, width, height, color):
        assert 0 <= x < self.w and 0 <= y < self.h
        assert 0 < width <= self.w - x and 0 < height <= self.h - y
        self.calls.append((x, y, width, height))

    def text(self, value, x, y, fg, bg, scale=1):
        assert 0 <= x <= self.w and 0 <= y <= self.h - 8 * scale
        assert len(value) * 8 * scale <= self.w - x, (value, x, self.w)
        self.texts.append(value)


class UILayoutTests(unittest.TestCase):
    def test_s3_prompt_scrolls_inside_right_panel_without_blocking_approval(self):
        with patch("builtins.open", return_value=io.StringIO("waveshare-s3-amoled-164-v2")):
            cfg = load("board_config")
        driver = types.SimpleNamespace(rgb=lambda r, g, b: (r << 16) | (g << 8) | b)
        with patch.dict(sys.modules, {"board_config": cfg, "st7789": driver}):
            ui_module = load("buddy_ui")
        display = BoundedDisplay(cfg.UI_WIDTH, cfg.UI_HEIGHT)
        player = Mock(available=False)
        ui = ui_module.BuddyUI(display, None, player)
        title = "Edit " + "x" * 100
        prompt = {"kind": "permission", "token": "per_1", "text": title,
                  "options": ["REFUSE", "AUTORISER UNE FOIS", "TOUJOURS AUTORISER"],
                  "selected": 0, "sent": False, "title_at": None, "option_at": None}
        buddy = Mock(kind="usb", state="permission", label="Approval pending",
                     passkey=None, confirm=False, hid_until=None,
                     secure=True, info="", prompt=types.SimpleNamespace(ready=lambda: prompt))
        buddy.online.return_value = True
        buddy.pairing_open.return_value = False
        with patch.object(ui_module.time, "ticks_diff", lambda a, b: a - b, create=True):
            ui.draw(buddy, 200_000)
            self.assertIn("SWIPE: CHOICE  TAP: ANSWER", display.texts)
            for now in range(200_350, 212_000, 350):
                ui.draw(buddy, now)
        self.assertIn("PERMISSION", display.texts)
        self.assertIn("REFUSE", display.texts)

    def test_all_states_and_pairing_fit_both_panels_with_and_without_pet(self):
        driver = types.SimpleNamespace(rgb=lambda r, g, b: (r << 16) | (g << 8) | b)
        for marker in ("waveshare-c6-lcd-147", "waveshare-s3-amoled-164-v2"):
            with self.subTest(board=marker), patch("builtins.open", return_value=io.StringIO(marker)):
                cfg = load("board_config")
            with patch.dict(sys.modules, {"board_config": cfg, "st7789": driver}):
                ui_module = load("buddy_ui")
            self.assertEqual(cfg.UI_BACKGROUND, (0, 0, 0))
            self.assertEqual(cfg.UI_DIVIDER_INSET, 0)
            self.assertEqual(ui_module.BACKGROUND, driver.rgb(*cfg.UI_BACKGROUND))
            for pet_ready in (False, True):
                with self.subTest(board=marker, pet_ready=pet_ready):
                    display = BoundedDisplay(cfg.UI_WIDTH, cfg.UI_HEIGHT)
                    player = Mock(available=pet_ready, source="internal")
                    player.draw.return_value = pet_ready
                    ui = ui_module.BuddyUI(display, None, player)
                    buddy = Mock(kind="usb", state="permission", label="Long label " * 4,
                                 passkey=None, confirm=False, hid_until=None,
                                 secure=True, info="123456789012345678901234")
                    buddy.online.return_value = True
                    buddy.pairing_open.return_value = False
                    for state in ui_module.LABELS:
                        buddy.state = state
                        ui.draw(buddy, 0)
                    buddy.passkey = 123456
                    ui.draw(buddy, 350)
                    self.assertIn((0, 0, display.w, display.h), display.calls)
                    self.assertIn((0, 0, display.w, 3), display.calls)
                    self.assertIn((cfg.UI_DIVIDER_INSET, cfg.UI_DIVIDER_Y,
                                   display.w - 2 * cfg.UI_DIVIDER_INSET, 1), display.calls)
                    if pet_ready:
                        player.draw.assert_called()
                    else:
                        self.assertIn(cfg.UI_PET_STAGE, display.calls)


if __name__ == "__main__":
    unittest.main()
