import builtins
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


FIRMWARE = Path(__file__).resolve().parents[1] / "c6lcd"


def load_module(name, dependencies=None, directory=FIRMWARE, **overrides):
    dependencies = dependencies or {}
    spec = importlib.util.spec_from_file_location("_amoled_test_" + name, directory / (name + ".py"))
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
        self.buses = []
        buses = self.buses
        pins, events = self.pins, self.events

        class FakePin:
            OUT = 1

            def __init__(self, number, mode=None, value=None):
                self.number, self.mode, self.value = number, mode, value
                pins[number] = self

            def __call__(self, value):
                self.value = value
                events.append(("pin", self.number, value))

        class FakeBus:
            def __init__(self, **kwargs):
                self.options = kwargs
                self.transactions = []
                self.payload_buffers = []
                self.deinit = Mock()
                self.fail_command = None
                buses.append(self)

            def write(self, command, data=None, quad=False):
                if command == self.fail_command:
                    raise OSError("Native transfer failed")
                self.transactions.append((command, None if data is None else bytes(data), quad))
                if quad:
                    self.payload_buffers.append(data.obj)

        machine = types.SimpleNamespace(Pin=FakePin, SPI=Mock(
            side_effect=AssertionError("AMOLED must not create machine.SPI")), PWM=Mock(
            side_effect=AssertionError("AMOLED must not create a backlight PWM")))
        clock = types.SimpleNamespace(sleep_ms=lambda ms: events.append(("sleep", ms)))
        self.framebuf = types.SimpleNamespace()
        shared = load_module("shared_spi", {"machine": machine, "board_config": cfg})
        self.renderer = load_module("st7789", {
            "machine": machine, "board_config": cfg, "shared_spi": shared,
            "framebuf": self.framebuf, "time": clock,
        })
        self.dependencies = {
            "machine": machine, "board_config": cfg, "st7789": self.renderer, "time": clock,
            "amoled_qspi": types.SimpleNamespace(Bus=FakeBus),
        }
        self.driver = load_module("co5300", self.dependencies)
        self.lcd = self.driver.LCD()
        self.addCleanup(self.lcd.close)

    @property
    def transactions(self):
        return self.lcd.bus.transactions

    def assert_window(self, left, top, right, bottom, pixels):
        self.assertEqual(self.transactions, [
            (0x2A, left.to_bytes(2, "big") + right.to_bytes(2, "big"), False),
            (0x2B, top.to_bytes(2, "big") + bottom.to_bytes(2, "big"), False),
            (0x2C, b"".join(pixels), True),
        ])

    def test_reset_initialization_and_native_quad_transport(self):
        self.assertEqual(self.events[:4], [
            ("pin", 21, 0), ("sleep", 10), ("pin", 21, 1), ("sleep", 150),
        ])
        self.assertEqual([event[1] for event in self.events if event[0] == "sleep"],
                         [10, 150, 80, 1, 1, 1, 10])
        self.assertEqual(self.transactions[:9], [
            (0x36, b"\x00", False), (0x3A, b"\x55", False),
            (0x11, None, False), (0xC4, b"\x80", False),
            (0x35, b"\x00", False), (0x53, b"\x20", False),
            (0x63, b"\xff", False), (0x51, b"\x00", False),
            (0x29, None, False),
        ])
        self.assertEqual(self.transactions[-1], (0x51, b"\x80", False))
        self.assertEqual(self.lcd.bus.options, {"baudrate": 10_000_000})
        self.assertEqual(set(self.pins), {21})

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

    def test_full_physical_clear_colors_and_reusable_contiguous_payload(self):
        scratch = self.lcd.transfer_buffer
        for color in (0xF800, 0x07E0, 0x001F, 0, 0xFFFF):
            with self.subTest(color=color):
                self.transactions.clear()
                self.lcd.clear_all(color)
                expected = color.to_bytes(2, "big") * (280 * 456)
                self.assert_window(20, 0, 299, 455, [expected])
                self.assertEqual(self.lcd.buffer, expected)
                self.assertIs(self.lcd.transfer_buffer, scratch)
        self.lcd.fill_rect(1, 1, 3, 5, 0x1234)
        self.assertTrue(all(buf is scratch for buf in self.lcd.bus.payload_buffers))

    def test_physical_bounds_and_edge_alignment(self):
        self.transactions.clear()
        for bounds in ((-1, 0, 1, 1), (0, -1, 1, 1), (280, 0, 1, 1),
                       (0, 456, 1, 1), (279, 455, 2, 1)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                self.lcd._flush(*bounds)
        self.assertEqual(self.transactions, [])
        self.lcd._flush(279, 455, 1, 1)
        self.assert_window(298, 454, 299, 455, [bytes(8)])

    def test_close_releases_native_bus_and_buffers_once(self):
        bus = self.lcd.bus
        self.lcd.close()
        self.lcd.close()
        bus.deinit.assert_called_once_with()
        for name in ("bus", "buffer", "view", "transfer_buffer", "transfer_view"):
            self.assertIsNone(getattr(self.lcd, name))

    def test_initialization_errors_release_bus(self):
        for command in (0x36, 0x2C, 0x51):
            bus_type = self.dependencies["amoled_qspi"].Bus

            def failing_bus(**kwargs):
                bus = bus_type(**kwargs)
                bus.fail_command = command
                return bus

            with self.subTest(command=command), \
                    patch.object(self.driver.amoled_qspi, "Bus", failing_bus):
                with self.assertRaisesRegex(OSError, "Native transfer failed"):
                    self.driver.LCD()
                self.buses[-1].deinit.assert_called_once_with()
        with self.assertRaises(ValueError):
            self.driver.LCD("portrait")
        self.buses[-1].deinit.assert_called_once_with()

    def test_reset_pin_failure_releases_bus(self):
        with patch.object(self.driver, "Pin", side_effect=OSError("Pin failed")):
            with self.assertRaisesRegex(OSError, "Pin failed"):
                self.driver.LCD()
        self.buses[-1].deinit.assert_called_once_with()

    def test_missing_native_module_has_actionable_import_error(self):
        dependencies = dict(self.dependencies, amoled_qspi=None)
        del dependencies["amoled_qspi"]
        original_import = builtins.__import__

        def missing_import(name, *args, **kwargs):
            if name == "amoled_qspi":
                raise ImportError("No module named amoled_qspi")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", missing_import):
            with self.assertRaisesRegex(ImportError, "install.*QSPI MicroPython firmware"):
                load_module("co5300", dependencies)

    def test_ram_tool_uses_full_physical_clear_and_closes(self):
        lcd = Mock()
        constructor = Mock(return_value=lcd)
        clock = types.SimpleNamespace(sleep_ms=Mock())
        cfg = types.SimpleNamespace(BOARD_MODEL="waveshare-s3-amoled-164",
                                    DISPLAY_DRIVER="co5300")
        tool = load_module("test_amoled", {
            "board_config": cfg, "time": clock,
            "co5300": types.SimpleNamespace(LCD=constructor, rgb=self.driver.rgb),
        }, directory=FIRMWARE.parent / "tools", print=Mock())
        tool.main()
        self.assertEqual([call.args for call in lcd.clear_all.call_args_list],
                         [(0xF800,), (0x07E0,), (0x001F,), (0,), (0xFFFF,), (0,)])
        self.assertEqual([call.args for call in clock.sleep_ms.call_args_list], [(1500,)] * 5)
        lcd.close.assert_called_once_with()
        lcd.reset_mock()
        lcd.clear_all.side_effect = OSError("Transfer failed")
        with self.assertRaisesRegex(OSError, "Transfer failed"):
            tool.main()
        lcd.close.assert_called_once_with()
        constructor.reset_mock()
        for model, driver in (("waveshare-c6-lcd-147", "st7789"),
                              ("waveshare-s3-amoled-164", "st7789")):
            cfg.BOARD_MODEL, cfg.DISPLAY_DRIVER = model, driver
            with self.assertRaisesRegex(RuntimeError, "board profile"):
                tool.main()
        constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
