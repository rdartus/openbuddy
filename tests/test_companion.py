"""Startup and teardown fault injection without a board, BLE or serial access."""

import io
import types
import unittest
from unittest.mock import MagicMock, Mock

from test_amoled import load_module


class Clock:
    def __init__(self):
        self.now = 0
        self.stop_at = 20

    def ticks_ms(self):
        return self.now

    @staticmethod
    def ticks_add(now, delta):
        return now + delta

    @staticmethod
    def ticks_diff(now, then):
        return now - then

    def sleep_ms(self, delay):
        self.now += delay
        if self.now >= self.stop_at:
            raise KeyboardInterrupt


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cfg = types.SimpleNamespace(DISPLAY_DRIVER="co5300", RGB_LED=None,
                                         BOOT_BUTTON=0, AUTO_ORIENTATION=True)
        self.lcd = Mock(orientation="landscape", w=320, h=172)
        self.buddy = Mock(confirm=None, passkey=None, diagnostics=["test BLE diagnostic"])
        self.buddy.pairing_open.return_value = False
        self.usb = Mock()
        self.usb.online.return_value = False
        self.orientation = Mock()
        self.orientation.poll.return_value = None
        self.player = Mock(available=True, source="internal", pet_id="test-pet")
        self.storage = Mock(mounted=False)
        self.storage.load_player.return_value = self.player
        self.ui = Mock()
        self.pin = Mock()
        self.pin.value.return_value = 1
        self.led = MagicMock()
        self.log = io.StringIO()
        context = MagicMock()
        context.__enter__.return_value = self.log
        self.open = Mock(return_value=context)
        self.os = types.SimpleNamespace(sync=Mock())

        def print_exception(error, handle=None):
            if handle is not None:
                handle.write(type(error).__name__ + ": " + str(error) + "\n")

        self.sys = types.SimpleNamespace(print_exception=Mock(side_effect=print_exception))
        self.deps = {
            "os": self.os, "sys": self.sys, "time": self.clock,
            "machine": types.SimpleNamespace(Pin=Mock(IN=0, PULL_UP=2, return_value=self.pin)),
            "board_config": self.cfg,
            "co5300": types.SimpleNamespace(LCD=Mock(return_value=self.lcd)),
            "st7789": types.SimpleNamespace(LCD=Mock(return_value=self.lcd)),
            "shared_spi": types.SimpleNamespace(SharedSPI=Mock()),
            "buddy_ble": types.SimpleNamespace(BuddyBLE=Mock(return_value=self.buddy)),
            "buddy_usb": types.SimpleNamespace(BuddyUSB=Mock(return_value=self.usb)),
            "buddy_ui": types.SimpleNamespace(BuddyUI=Mock(return_value=self.ui)),
            "storage": types.SimpleNamespace(Storage=Mock(return_value=self.storage)),
            "buddy_orientation": types.SimpleNamespace(
                FLIP={"landscape": "landscape_inv", "landscape_inv": "landscape"},
                AutoOrientation=Mock(return_value=self.orientation)),
            "neopixel": types.SimpleNamespace(NeoPixel=Mock(return_value=self.led)),
        }
        self.firmware = load_module("companion", self.deps, open=self.open, print=Mock())
        self.firmware.load_orientation = Mock(return_value="landscape")
        self.firmware.save_orientation = Mock()

    def run_until_interrupt(self):
        with self.assertRaises(KeyboardInterrupt):
            self.firmware.run()

    def assert_all_closed(self):
        for resource in (self.orientation, self.buddy, self.player, self.storage, self.lcd):
            resource.close.assert_called_once_with()

    def test_ctrl_c_closes_display_after_storage_without_writing_error_log(self):
        order = []
        for name, resource in (("orientation", self.orientation), ("BLE", self.buddy),
                               ("player", self.player), ("storage", self.storage),
                               ("display", self.lcd)):
            resource.close.side_effect = lambda name=name: order.append(name)
        self.run_until_interrupt()
        self.assert_all_closed()
        self.assertEqual(order, ["orientation", "BLE", "player", "storage", "display"])
        self.open.assert_not_called()

    def test_display_startup_error_is_logged_without_drawing_on_failed_bus(self):
        primary = OSError("display init failed")
        self.deps["co5300"].LCD.side_effect = primary
        with self.assertRaises(OSError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assertIn("Stage: display", self.log.getvalue())
        self.assertIn("display init failed", self.log.getvalue())
        self.deps["buddy_usb"].BuddyUSB.assert_not_called()
        self.lcd.fill_rect.assert_not_called()
        self.lcd.text.assert_not_called()

    def test_import_error_is_logged_before_hardware_initialization(self):
        importer = self.firmware.__dict__["__builtins__"]["__import__"]
        primary = ImportError("profile unavailable")

        def import_module(name, *args, **kwargs):
            if name == "board_config":
                raise primary
            return importer(name, *args, **kwargs)

        self.firmware.__dict__["__builtins__"]["__import__"] = import_module
        with self.assertRaises(ImportError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assertIn("Stage: imports", self.log.getvalue())
        self.deps["co5300"].LCD.assert_not_called()

    def test_assets_failure_still_closes_lcd_and_other_initialized_resources(self):
        primary = ValueError("asset startup failed")
        self.storage.load_player.side_effect = primary
        with self.assertRaises(ValueError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assertIn("Stage: assets", self.log.getvalue())
        self.orientation.close.assert_called_once_with()
        self.storage.close.assert_called_once_with()
        self.lcd.close.assert_called_once_with()
        self.player.close.assert_not_called()

    def test_led_startup_failure_still_closes_display(self):
        self.cfg.RGB_LED = 8
        primary = OSError("LED startup failed")
        self.led.write.side_effect = [primary, None]
        with self.assertRaises(OSError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assertIn("Stage: LED", self.log.getvalue())
        self.lcd.close.assert_called_once_with()
        self.assertEqual(self.led.write.call_count, 2)

    def test_ui_startup_failure_closes_every_initialized_resource(self):
        primary = OSError("UI startup failed")
        self.deps["buddy_ui"].BuddyUI.side_effect = primary
        with self.assertRaises(OSError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assertIn("Stage: UI", self.log.getvalue())
        self.assert_all_closed()

    def test_runtime_qspi_error_is_not_followed_by_any_error_screen_io(self):
        primary = OSError("QSPI transfer failed")
        self.ui.draw.side_effect = primary
        with self.assertRaises(OSError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assertIn("Stage: main loop", self.log.getvalue())
        self.assertIn("test BLE diagnostic", self.log.getvalue())
        self.lcd.fill_rect.assert_not_called()
        self.lcd.text.assert_not_called()
        self.assert_all_closed()

    def test_cleanup_failures_do_not_skip_lcd_or_replace_original_journal(self):
        primary = RuntimeError("primary runtime failure")
        self.ui.draw.side_effect = primary
        for resource in (self.orientation, self.buddy, self.player, self.storage, self.lcd):
            resource.close.side_effect = OSError("secondary cleanup failure")
        with self.assertRaises(RuntimeError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)
        self.assert_all_closed()
        self.open.assert_called_once_with("openbuddy-error.txt", "w")
        self.assertIn("primary runtime failure", self.log.getvalue())
        self.assertNotIn("secondary cleanup failure", self.log.getvalue())

    def test_full_filesystem_and_broken_serial_logging_do_not_mask_primary_error(self):
        primary = OSError("primary display failure")
        self.deps["co5300"].LCD.side_effect = primary
        self.open.side_effect = OSError("filesystem full")
        self.sys.print_exception.side_effect = OSError("serial unavailable")
        with self.assertRaises(OSError) as error:
            self.firmware.run()
        self.assertIs(error.exception, primary)

    def test_ble_failure_keeps_usb_and_manual_rotation_usable_even_offline(self):
        self.deps["buddy_ble"].BuddyBLE.side_effect = OSError("BLE startup failed")
        self.clock.stop_at = 180
        self.pin.value.side_effect = lambda: int(not 20 <= self.clock.now < 80)
        self.run_until_interrupt()
        self.assertIn("Stage: BLE", self.log.getvalue())
        self.assertGreater(self.usb.tick.call_count, 1)
        self.assertTrue(all(call.args[0] is self.usb for call in self.ui.draw.call_args_list))
        self.lcd.set_orientation.assert_called_once_with("landscape_inv")
        self.firmware.save_orientation.assert_called_once_with("landscape_inv")
        self.buddy.tick.assert_not_called()
        self.buddy.close.assert_not_called()
        self.lcd.close.assert_called_once_with()

    def test_missing_bluetooth_module_also_falls_back_to_usb(self):
        importer = self.firmware.__dict__["__builtins__"]["__import__"]

        def import_module(name, *args, **kwargs):
            if name == "buddy_ble":
                raise ImportError("bluetooth unavailable")
            return importer(name, *args, **kwargs)

        self.firmware.__dict__["__builtins__"]["__import__"] = import_module
        self.run_until_interrupt()
        self.assertIn("Stage: BLE", self.log.getvalue())
        self.assertIn("bluetooth unavailable", self.log.getvalue())
        self.usb.tick.assert_called_once()
        self.ui.draw.assert_called_once_with(self.usb, 0)
        self.lcd.close.assert_called_once_with()

    def test_long_boot_without_ble_does_not_crash_or_trigger_rotation(self):
        self.deps["buddy_ble"].BuddyBLE.side_effect = OSError("BLE startup failed")
        self.clock.stop_at = 3400
        self.pin.value.side_effect = lambda: int(not 20 <= self.clock.now < 3200)
        self.run_until_interrupt()
        self.assertGreater(self.usb.tick.call_count, 150)
        self.lcd.set_orientation.assert_not_called()
        self.firmware.save_orientation.assert_not_called()
        self.assertNotIn("main loop", self.log.getvalue())

    def test_usb_is_initialized_before_ble_and_usb_failure_still_releases_lcd(self):
        self.deps["buddy_usb"].BuddyUSB.side_effect = OSError("USB startup failed")
        with self.assertRaisesRegex(OSError, "USB startup failed"):
            self.firmware.run()
        self.assertIn("Stage: USB", self.log.getvalue())
        self.deps["buddy_ble"].BuddyBLE.assert_not_called()
        self.lcd.close.assert_called_once_with()

    def test_c6_led_cleanup_failure_does_not_replace_keyboard_interrupt(self):
        self.cfg.DISPLAY_DRIVER = "st7789"
        self.cfg.RGB_LED = 8
        self.led.write.side_effect = [None, OSError("LED cleanup failed")]
        self.run_until_interrupt()
        self.assert_all_closed()
        self.assertEqual(self.led.__setitem__.call_args.args, (0, (0, 0, 0)))
        self.open.assert_not_called()

    def test_lcd_without_close_method_keeps_c6_cleanup_compatible(self):
        self.cfg.DISPLAY_DRIVER = "st7789"
        self.deps["st7789"].LCD.return_value = types.SimpleNamespace(orientation="landscape")
        self.run_until_interrupt()
        self.storage.close.assert_called_once_with()
        self.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
