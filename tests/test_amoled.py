import builtins
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


FIRMWARE = Path(__file__).resolve().parents[1] / "c6lcd"


def load_module(name, dependencies=None, **overrides):
    dependencies = dependencies or {}
    spec = importlib.util.spec_from_file_location("_amoled_test_" + name, FIRMWARE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)

    def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in dependencies:
            return dependencies[name]
        return builtins.__import__(name, globals, locals, fromlist, level)

    module.__dict__["__builtins__"] = dict(vars(builtins), __import__=isolated_import, **overrides)
    spec.loader.exec_module(module)
    return module


class AMOLEDTests(unittest.TestCase):
    def setUp(self):
        cfg = load_module("board_config", open=Mock(return_value=io.StringIO(
            "waveshare-s3-amoled-164\n")))
        self.pins = {}
        self.events = []
        pins, events = self.pins, self.events

        class FakePin:
            OUT = 1

            def __init__(self, number, mode=None, value=None):
                self.number, self.mode, self.value = number, mode, value
                self.transactions = []
                pins[number] = self

            def __call__(self, value):
                self.value = value
                events.append(("pin", self.number, value))
                if value == 0:
                    self.transactions.append([])

        class FakeSPI:
            def __init__(self, number, **kwargs):
                self.number, self.options = number, kwargs

            def write(self, data):
                cs = pins[cfg.LCD_CS]
                if cs.value != 0:
                    raise AssertionError("SPI write while chip select is high")
                cs.transactions[-1].append(bytes(data))

        machine = types.SimpleNamespace(Pin=FakePin, SPI=FakeSPI, PWM=Mock(
            side_effect=AssertionError("AMOLED must not create a backlight PWM")))
        clock = types.SimpleNamespace(sleep_ms=lambda ms: events.append(("sleep", ms)))
        self.framebuf = types.SimpleNamespace()
        shared = load_module("shared_spi", {"machine": machine, "board_config": cfg})
        self.renderer = load_module("st7789", {
            "machine": machine, "board_config": cfg, "shared_spi": shared,
            "framebuf": self.framebuf, "time": clock,
        })
        self.driver = load_module("co5300", {
            "machine": machine, "board_config": cfg, "st7789": self.renderer, "time": clock,
        })
        self.lcd = self.driver.LCD()

    @property
    def transactions(self):
        return self.lcd.cs.transactions

    def assert_window(self, left, top, right, bottom, pixels):
        self.assertEqual(self.transactions, [
            [b"\x02\x00\x2a\x00", left.to_bytes(2, "big") + right.to_bytes(2, "big")],
            [b"\x02\x00\x2b\x00", top.to_bytes(2, "big") + bottom.to_bytes(2, "big")],
            [b"\x02\x00\x2c\x00"] + pixels,
        ])
        self.assertEqual(self.lcd.cs.value, 1)

    def test_reset_initialization_and_single_lane_command_framing(self):
        self.assertEqual(self.events[:4], [
            ("pin", 21, 0), ("sleep", 10), ("pin", 21, 1), ("sleep", 150),
        ])
        self.assertEqual([event[1] for event in self.events if event[0] == "sleep"],
                         [10, 150, 80, 1, 1, 1, 10])
        self.assertEqual(self.transactions[:9], [
            [b"\x02\x00\x36\x00", b"\x00"],
            [b"\x02\x00\x3a\x00", b"\x55"],
            [b"\x02\x00\x11\x00"],
            [b"\x02\x00\xc4\x00", b"\x80"],
            [b"\x02\x00\x35\x00", b"\x00"],
            [b"\x02\x00\x53\x00", b"\x20"],
            [b"\x02\x00\x63\x00", b"\xff"],
            [b"\x02\x00\x51\x00", b"\x00"],
            [b"\x02\x00\x29\x00"],
        ])
        self.assertEqual(self.transactions[-1], [b"\x02\x00\x51\x00", b"\x80"])
        for transaction in self.transactions:
            self.assertEqual(len(transaction[0]), 4)
            self.assertEqual(transaction[0][::3], b"\x02\x00")
            self.assertEqual(transaction[0][1], 0)
            self.assertNotEqual(transaction[0][0], 0x32)
        self.assertEqual(self.lcd.spi.number, 1)
        self.assertEqual({key: self.lcd.spi.options[key] for key in (
            "baudrate", "polarity", "phase", "miso")},
            {"baudrate": 10_000_000, "polarity": 0, "phase": 0, "miso": None})
        self.assertEqual(self.lcd.spi.options["sck"].number, 10)
        self.assertEqual(self.lcd.spi.options["mosi"].number, 11)
        self.assertEqual(set(self.pins), {9, 21, 10, 11})

    def test_initial_clear_covers_panel_with_twenty_column_offset(self):
        self.assertEqual((self.lcd.w, self.lcd.h), (320, 172))
        self.assertEqual(len(self.lcd.buffer), 280 * 456 * 2)
        self.transactions[:] = self.transactions[9:12]
        self.assert_window(20, 0, 299, 455, [bytes(560)] * 456)

    def test_blit_rotates_both_orientations_without_swapping_rgb565_bytes(self):
        source = b"\xf8\x00\x07\xe0\x00\x1f\x12\x34\xab\xcd\xff\xff"
        cases = (
            ("landscape", 74, 384, [bytes(4), b"\x00\x1f\xff\xff", b"\x07\xe0\xab\xcd",
                                     b"\xf8\x00\x12\x34"]),
            ("landscape_inv", 244, 68, [b"\x12\x34\xf8\x00", b"\xab\xcd\x07\xe0",
                                        b"\xff\xff\x00\x1f", bytes(4)]),
        )
        for orientation, left, top, rows in cases:
            with self.subTest(orientation=orientation):
                self.lcd.set_orientation(orientation)
                self.transactions.clear()
                self.lcd.blit(source, 0, 0, 3, 2)
                self.assert_window(left, top, left + 1, top + 3, rows)

    def test_odd_updates_flush_even_bounds_and_preserve_shadow_neighbours(self):
        for orientation, x, y in (("landscape", 54, 386), ("landscape_inv", 224, 68)):
            with self.subTest(orientation=orientation):
                self.lcd.set_orientation(orientation)
                self.lcd.fill_rect(0, 0, 2, 2, 0x1234)
                self.transactions.clear()
                self.lcd.blit(b"\xab\xcd", 0, 1, 1, 1)
                rows = ([b"\x12\x34\x12\x34", b"\x12\x34\xab\xcd"]
                        if orientation == "landscape" else
                        [b"\xab\xcd\x12\x34", b"\x12\x34\x12\x34"])
                self.assert_window(x + 20, y, x + 21, y + 1, rows)
                self.transactions.clear()
                self.lcd.fill_rect(1, 0, 1, 1, 0xF800)
                rows = ([b"\xf8\x00\x12\x34", b"\x12\x34\xab\xcd"]
                        if orientation == "landscape" else
                        [b"\xab\xcd\x12\x34", b"\x12\x34\xf8\x00"])
                self.assert_window(x + 20, y, x + 21, y + 1, rows)

    def test_logical_corners_stay_inside_centered_canvas(self):
        cases = {
            "landscape": [(54, 387), (54, 68), (225, 387), (225, 68)],
            "landscape_inv": [(225, 68), (225, 387), (54, 68), (54, 387)],
        }
        for orientation, expected in cases.items():
            self.lcd.set_orientation(orientation)
            for (x, y), (px, py) in zip(((0, 0), (319, 0), (0, 171), (319, 171)), expected):
                with self.subTest(orientation=orientation, point=(x, y)):
                    self.transactions.clear()
                    self.lcd.blit(b"\x56\x78", x, y, 1, 1)
                    start = (py * 280 + px) * 2
                    self.assertEqual(self.lcd.buffer[start:start + 2], b"\x56\x78")
                    left, top = px & ~1, py & ~1
                    rows = [bytearray(4), bytearray(4)]
                    rows[py - top][(px - left) * 2:(px - left) * 2 + 2] = b"\x56\x78"
                    self.assert_window(left + 20, top, left + 21, top + 1, rows)

    def test_orientation_change_clears_shadow_and_rejects_unsupported_names(self):
        self.lcd.fill_rect(0, 0, 1, 1, 0xFFFF)
        self.transactions.clear()
        self.lcd.set_orientation("landscape_inv")
        self.assertFalse(any(self.lcd.buffer))
        self.assert_window(20, 0, 299, 455, [bytes(560)] * 456)
        self.transactions.clear()
        for orientation in ("portrait", "portrait_inv", "unknown", None):
            with self.subTest(orientation=orientation), self.assertRaises(ValueError):
                self.lcd.set_orientation(orientation)
        self.assertEqual(self.lcd.orientation, "landscape_inv")
        self.assertEqual(self.transactions, [])

    def test_invalid_bounds_and_buffer_sizes_fail_without_io_or_shadow_changes(self):
        self.transactions.clear()
        before = bytes(self.lcd.buffer)
        for bounds in ((-1, 0, 1, 1), (0, -1, 1, 1), (320, 0, 1, 1),
                       (0, 172, 1, 1), (319, 0, 2, 1), (0, 171, 1, 2)):
            with self.subTest(bounds=bounds):
                with self.assertRaises(ValueError):
                    self.lcd.blit(bytes(bounds[2] * bounds[3] * 2), *bounds)
                with self.assertRaises(ValueError):
                    self.lcd.fill_rect(*bounds, 0xFFFF)
        for size in (0, 1, 7, 9):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.lcd.blit(bytes(size), 0, 0, 2, 2)
        self.assertEqual(self.transactions, [])
        self.assertEqual(self.lcd.buffer, before)

    def test_nonpositive_sizes_are_noops(self):
        self.transactions.clear()
        for w, h in ((0, 1), (1, 0), (-1, 1), (1, -1)):
            self.lcd.blit(b"", 0, 0, w, h)
            self.lcd.fill_rect(0, 0, w, h, 0xFFFF)
        self.assertEqual(self.transactions, [])
        self.assertFalse(any(self.lcd.buffer))

    def test_text_and_rgb_are_inherited_without_initializing_st7789(self):
        self.assertTrue(issubclass(self.driver.LCD, self.renderer.LCD))
        self.assertIs(self.driver.LCD.text, self.renderer.LCD.text)
        self.assertIs(self.driver.rgb, self.renderer.rgb)
        self.assertEqual(self.driver.rgb(255, 0, 0), 0xF800)
        self.transactions.clear()
        self.lcd.text("", 0, 0, 0xFFFF, 0)
        self.assertEqual(self.transactions, [])
        self.assertFalse(hasattr(self.framebuf, "FrameBuffer"))


if __name__ == "__main__":
    unittest.main()
