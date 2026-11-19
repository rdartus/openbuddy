import builtins
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


FIRMWARE = Path(__file__).resolve().parents[1] / "device"


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
    BOARD = "waveshare-s3-amoled-164-v2"

    def setUp(self):
        cfg = load_module("board_config", open=Mock(return_value=io.StringIO(
            self.BOARD + "\n")))
        self.cfg = cfg
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
                self.native_calls = []
                self.deinit = Mock()
                self.fail_command = None
                buses.append(self)

            def write(self, command, data=None, quad=False):
                if command == self.fail_command:
                    raise OSError("Native transfer failed")
                self.transactions.append((command, None if data is None else bytes(data), quad))
                if quad:
                    self.payload_buffers.append(data.obj)

            def fill_buffer(self, shadow, color):
                self.native_calls.append("fill_buffer")
                shadow[:] = color.to_bytes(2, "big") * (280 * 456)

            def fill_rect(self, shadow, x, y, w, h, color):
                self.native_calls.append("fill_rect")
                for row in range(y, y + h):
                    start = (row * 280 + x) * 2
                    shadow[start:start + w * 2] = color.to_bytes(2, "big") * w

            def blit_rotated(self, shadow, source, x, y, w, h, inverted, scale, canvas_w, canvas_h):
                self.native_calls.append("blit_rotated")
                for row in range(h):
                    for column in range(w):
                        offset = (row * w + column) * 2
                        for sy in range(scale):
                            for sx in range(scale):
                                px = (280 - canvas_h) // 2 + (canvas_h - 1 - y - row * scale - sy
                                                              if inverted else y + row * scale + sy)
                                py = (456 - canvas_w) // 2 + (x + column * scale + sx if inverted
                                                              else canvas_w - 1 - x - column * scale - sx)
                                target = (py * 280 + px) * 2
                                shadow[target:target + 2] = source[offset:offset + 2]

            def pack_rect(self, shadow, scratch, x, y, w, h):
                self.native_calls.append("pack_rect")
                for row in range(h):
                    start = ((y + row) * 280 + x) * 2
                    scratch[row * w * 2:(row + 1) * w * 2] = shadow[start:start + w * 2]

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
            "amoled_qspi": types.SimpleNamespace(Bus=FakeBus, API_VERSION=4),
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
        self.assertEqual(self.lcd.bus.options, {"baudrate": self.cfg.LCD_SPI_BAUD,
                                              "cs": self.cfg.LCD_CS})
        self.assertEqual(set(self.pins), {21})

    def test_initial_clear_covers_panel_with_twenty_column_offset(self):
        self.assertEqual((self.lcd.w, self.lcd.h), (self.cfg.UI_WIDTH, self.cfg.UI_HEIGHT))
        self.assertEqual(len(self.lcd.buffer), 280 * 456 * 2)
        self.transactions[:] = self.transactions[9:12]
        self.assert_window(20, 0, 299, 455, [bytes(560)] * 456)

    def test_blit_rotates_both_orientations_without_swapping_rgb565_bytes(self):
        source = b"\xf8\x00\x07\xe0\x00\x1f\x12\x34\xab\xcd\xff\xff"
        for orientation in ("landscape", "landscape_inv"):
            with self.subTest(orientation=orientation):
                self.lcd.set_orientation(orientation)
                self.transactions.clear()
                self.lcd.blit(source, 0, 0, 3, 2)
                for row in range(2):
                    for col in range(3):
                        px, py = self.lcd._point(col, row)
                        self.assertEqual(self.lcd.buffer[(py * 280 + px) * 2:(py * 280 + px) * 2 + 2],
                                         source[(row * 3 + col) * 2:(row * 3 + col) * 2 + 2])
                self.assertEqual(len(self.transactions), 3)

    def test_odd_updates_flush_even_bounds_and_preserve_shadow_neighbours(self):
        for orientation in ("landscape", "landscape_inv"):
            with self.subTest(orientation=orientation):
                self.lcd.set_orientation(orientation)
                self.lcd.fill_rect(0, 0, 2, 2, 0x1234)
                self.transactions.clear()
                self.lcd.blit(b"\xab\xcd", 0, 1, 1, 1)
                self.assertEqual(self.lcd.buffer[(self.lcd._point(0, 1)[1] * 280 +
                                                   self.lcd._point(0, 1)[0]) * 2:][:2], b"\xab\xcd")
                self.assertEqual(self.transactions[0][0], 0x2A)
                self.assertEqual(self.transactions[1][0], 0x2B)
                self.transactions.clear()
                self.lcd.fill_rect(1, 0, 1, 1, 0xF800)
                px, py = self.lcd._point(1, 0)
                self.assertEqual(self.lcd.buffer[(py * 280 + px) * 2:(py * 280 + px) * 2 + 2],
                                 b"\xf8\x00")

    def test_logical_corners_stay_inside_canvas(self):
        for orientation in ("landscape", "landscape_inv"):
            self.lcd.set_orientation(orientation)
            for x, y in ((0, 0), (self.lcd.w - 1, 0), (0, self.lcd.h - 1),
                         (self.lcd.w - 1, self.lcd.h - 1)):
                with self.subTest(orientation=orientation, point=(x, y)):
                    px, py = self.lcd._point(x, y)
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
        for bounds in ((-1, 0, 1, 1), (0, -1, 1, 1), (self.lcd.w, 0, 1, 1),
                       (0, self.lcd.h, 1, 1), (self.lcd.w - 1, 0, 2, 1),
                       (0, self.lcd.h - 1, 1, 2)):
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
            self.assertIs(self.lcd.bus.payload_buffers[-1], self.lcd.buffer)
        self.lcd.fill_rect(1, 1, 3, 5, 0x1234)
        self.assertIs(self.lcd.bus.payload_buffers[-1], scratch)
        self.lcd.blit(b"\x12\x34", 0, 0, 1, 1)
        self.assertIn("fill_buffer", self.lcd.bus.native_calls)
        self.assertIn("fill_rect", self.lcd.bus.native_calls)
        self.assertIn("blit_rotated", self.lcd.bus.native_calls)
        self.assertIn("pack_rect", self.lcd.bus.native_calls)

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

    def test_initialization_error_survives_native_cleanup_failure(self):
        bus_type = self.dependencies["amoled_qspi"].Bus

        def failing_bus(**kwargs):
            bus = bus_type(**kwargs)
            bus.deinit.side_effect = OSError("Native cleanup failed")
            return bus

        primary = OSError("Primary reset pin failure")
        with patch.object(self.driver.amoled_qspi, "Bus", failing_bus), \
                patch.object(self.driver, "Pin", side_effect=primary):
            with self.assertRaises(OSError) as error:
                self.driver.LCD()
        self.assertIs(error.exception, primary)
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

    def test_old_api_is_rejected_before_touching_the_display(self):
        old = types.SimpleNamespace(Bus=Mock(side_effect=AssertionError("Outdated bus used")),
                                    API_VERSION=3)
        with self.assertRaisesRegex(ImportError, "API_VERSION >= 4"):
            load_module("co5300", dict(self.dependencies, amoled_qspi=old))
        old.Bus.assert_not_called()

    def test_ram_tool_uses_full_physical_clear_and_closes(self):
        lcd = Mock()
        constructor = Mock(return_value=lcd)
        clock = types.SimpleNamespace(sleep_ms=Mock())
        cfg = types.SimpleNamespace(BOARD_MODEL=self.BOARD,
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
        for model, driver in (("waveshare-c6-lcd-147", "st7789"),):
            cfg.BOARD_MODEL, cfg.DISPLAY_DRIVER = model, driver
            with self.assertRaisesRegex(RuntimeError, "board profile"):
                tool.main()
        constructor.assert_not_called()


class AMOLEDV2Tests(AMOLEDTests):
    BOARD = "waveshare-s3-amoled-164-v2"

    def test_v2_bus_selects_gpio46_at_vendor_clock(self):
        self.assertEqual(self.lcd.bus.options, {"baudrate": 40_000_000, "cs": 46})

    def test_full_screen_and_scaled_pet_reach_panel_edges(self):
        for orientation in ("landscape", "landscape_inv"):
            self.lcd.set_orientation(orientation)
            self.lcd.fill_rect(0, 0, self.lcd.w, self.lcd.h, 0x1234)
            self.assertEqual(self.lcd.buffer[:2], b"\x12\x34")
            self.assertEqual(self.lcd.buffer[-2:], b"\x12\x34")
            self.lcd.blit(b"\xf8\x00\x07\xe0", 8, 36, 2, 1, scale=2)
            for row in range(2):
                for col in range(4):
                    px, py = self.lcd._point(8 + col, 36 + row)
                    self.assertEqual(self.lcd.buffer[(py * 280 + px) * 2:(py * 280 + px) * 2 + 2],
                                     b"\xf8\x00" if col < 2 else b"\x07\xe0")

    def test_both_landscape_bars_reach_physical_panel_edges(self):
        for orientation in ("landscape", "landscape_inv"):
            with self.subTest(orientation=orientation):
                self.lcd.set_orientation(orientation)
                self.lcd.fill_rect(0, 0, self.lcd.w, 3, 0xF800)
                self.lcd.fill_rect(0, self.cfg.UI_DIVIDER_Y, self.lcd.w, 1, 0x07E0)
                for x in (0, self.lcd.w - 1):
                    for y, expected in ((0, b"\xf8\x00"),
                                        (self.cfg.UI_DIVIDER_Y, b"\x07\xe0")):
                        px, py = self.lcd._point(x, y)
                        self.assertEqual(self.lcd.buffer[(py * self.lcd.WIDTH + px) * 2:][:2],
                                         expected)


if __name__ == "__main__":
    unittest.main()
