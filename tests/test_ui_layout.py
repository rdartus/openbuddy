"""Check both profile layouts without a board, display driver or pet assets."""

import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


FIRMWARE = Path(__file__).resolve().parents[1] / "device"


def board_file(name, board):
    if name == "openbuddy-board.txt":
        return io.StringIO(board)
    raise OSError("no storage preference")


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
        with patch("builtins.open", side_effect=lambda name: board_file(name, "waveshare-s3-amoled-164-v2")):
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
            self.assertIn("GLISSER: CHOIX  VALIDER: APPUI 1s SUR CHOIX", display.texts)
            for now in range(200_150, 212_000, 150):
                ui.draw(buddy, now)
        self.assertIn("PERMISSION", display.texts)
        self.assertIn("DEMANDE", display.texts)
        self.assertIn("CHOIX 1 SUR 3", display.texts)
        self.assertTrue(any(text.strip() == "REFUSE" for text in display.texts))
        self.assertIn((cfg.UI_TEXT_X - 4, cfg.UI_DETAIL_Y + 70,
                       cfg.UI_WIDTH - cfg.UI_TEXT_X + 4, 1), display.calls)

    def test_s3_request_and_choice_marquees_fit_without_page_counters(self):
        with patch("builtins.open", side_effect=lambda name: board_file(name, "waveshare-s3-amoled-164-v2")):
            cfg = load("board_config")
        driver = types.SimpleNamespace(rgb=lambda r, g, b: (r << 16) | (g << 8) | b)
        with patch.dict(sys.modules, {"board_config": cfg, "st7789": driver}):
            ui_module = load("buddy_ui")
        display = BoundedDisplay(cfg.UI_WIDTH, cfg.UI_HEIGHT)
        ui = ui_module.BuddyUI(display, None, Mock(available=False))
        title = "ACTION: " + "p" * 90 + " - ALWAYS: *.py"
        prompt = {"kind": "permission", "token": "per_2", "text": title,
                  "options": ["REFUSE", "AUTORISER UNE FOIS", "TOUJOURS AUTORISER " + "z" * 50],
                  "selected": 0, "position": 2, "total": 3,
                  "sent": False, "title_at": None, "option_at": None}
        buddy = Mock(kind="usb", state="permission", label="Approval pending",
                     passkey=None, confirm=False, hid_until=None,
                     secure=True, info="", prompt=types.SimpleNamespace(ready=lambda: prompt))
        buddy.online.return_value = True
        buddy.pairing_open.return_value = False
        with patch.object(ui_module.time, "ticks_diff", lambda a, b: a - b, create=True):
            for now in range(0, (len(title) + 20) * ui_module.MARQUEE_STEP_MS,
                             ui_module.MARQUEE_STEP_MS):
                ui.draw(buddy, now)
            full_clears = display.calls.count((0, 0, display.w, display.h))
            before_move = len(display.calls)
            prompt["selected"] = 2
            prompt["option_at"] = None
            for now in range(30_000, 40_000, ui_module.MARQUEE_STEP_MS):
                ui.draw(buddy, now)
        self.assertEqual(display.calls.count((0, 0, display.w, display.h)), full_clears)
        self.assertNotIn((cfg.UI_TEXT_X, cfg.UI_DETAIL_Y + 74,
                          display.w - cfg.UI_TEXT_X, 8), display.calls[before_move:])
        self.assertIn("DEMANDE 2 SUR 3", display.texts)
        self.assertIn("CHOIX 3 SUR 3", display.texts)
        self.assertIn("H: CHOIX V: DEMANDE  VALIDER: APPUI 1s SUR CHOIX", display.texts)
        self.assertTrue(any("ALWAYS: *.py" in text for text in display.texts))
        self.assertTrue(any("TOUJOURS AUTORISER" in text for text in display.texts))
        self.assertFalse(any(text.startswith("TEXT ") or text.startswith("CHOICE ")
                             or text == "3/3" for text in display.texts))

    def test_marquee_moves_right_to_left_and_short_text_stays_still(self):
        driver = types.SimpleNamespace(rgb=lambda r, g, b: (r << 16) | (g << 8) | b)
        with patch("builtins.open", side_effect=lambda name: board_file(name, "waveshare-s3-amoled-164-v2")):
            cfg = load("board_config")
        with patch.dict(sys.modules, {"st7789": driver, "board_config": cfg}):
            ui_module = load("buddy_ui")
        self.assertEqual(ui_module.marquee("REFUSE", 28, 99_000), "REFUSE")
        text, width = "ABCDEFGHIJKL", 5
        step = ui_module.MARQUEE_STEP_MS
        hold = ui_module.MARQUEE_HOLD_STEPS
        self.assertEqual(ui_module.marquee(text, width, 0), "ABCDE")
        self.assertEqual(ui_module.marquee(text, width, hold * step), "ABCDE")
        self.assertEqual(ui_module.marquee(text, width, (hold + 1) * step), "BCDEF")
        self.assertEqual(ui_module.marquee(text, width, (hold + len(text) - width) * step), "HIJKL")
        self.assertEqual(ui_module.marquee(text, width, (hold + len(text)) * step), " " * width)
        self.assertEqual(ui_module.marquee(text, width, (hold + len(text) + 8) * step), "ABCDE")

    def test_firmware_text_path_avoids_cpython_only_string_methods(self):
        source = (FIRMWARE / "buddy_ui.py").read_text(encoding="utf-8")
        self.assertNotIn(".ljust(", source)  # Absent from MicroPython str on the S3.

    def test_s3_marquee_overwrites_text_without_blanking_it_first(self):
        with patch("builtins.open", side_effect=lambda name: board_file(name, "waveshare-s3-amoled-164-v2")):
            cfg = load("board_config")
        driver = types.SimpleNamespace(rgb=lambda r, g, b: (r << 16) | (g << 8) | b)
        with patch.dict(sys.modules, {"board_config": cfg, "st7789": driver}):
            ui_module = load("buddy_ui")
        display = BoundedDisplay(cfg.UI_WIDTH, cfg.UI_HEIGHT)
        ui = ui_module.BuddyUI(display, None, Mock(available=False))
        prompt = {"kind": "form", "token": "f", "text": "Q" * 100,
                  "options": ["A" * 70, "B"], "selected": 0, "sent": False,
                  "title_at": None, "option_at": None}
        buddy = Mock(kind="usb", state="question", label="Question pending",
                     passkey=None, confirm=False, hid_until=None,
                     secure=True, info="", prompt=types.SimpleNamespace(ready=lambda: prompt))
        buddy.online.return_value = True
        buddy.pairing_open.return_value = False
        with patch.object(ui_module.time, "ticks_diff", lambda a, b: a - b, create=True):
            ui.draw(buddy, 0)
            before = len(display.calls)
            ui.draw(buddy, (ui_module.MARQUEE_HOLD_STEPS + 2) * ui_module.MARQUEE_STEP_MS)
        cleared = display.calls[before:]
        self.assertNotIn((cfg.UI_TEXT_X, cfg.UI_DETAIL_Y + 17, display.w - cfg.UI_TEXT_X, 8), cleared)
        self.assertNotIn((cfg.UI_TEXT_X, cfg.UI_DETAIL_Y + 74, display.w - cfg.UI_TEXT_X, 8), cleared)

    def test_all_states_and_pairing_fit_both_panels_with_and_without_pet(self):
        driver = types.SimpleNamespace(rgb=lambda r, g, b: (r << 16) | (g << 8) | b)
        for marker in ("waveshare-c6-lcd-147", "waveshare-s3-amoled-164-v2"):
            with self.subTest(board=marker), patch("builtins.open", side_effect=lambda name: board_file(name, marker)):
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
