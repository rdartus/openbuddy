import builtins
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, call


FIRMWARE = Path(__file__).resolve().parents[1] / "device"


def load_module(name, dependencies=None, **overrides):
    dependencies = dependencies or {}
    spec = importlib.util.spec_from_file_location("_storage_test_" + name, FIRMWARE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)

    def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in dependencies:
            return dependencies[name]
        return builtins.__import__(name, globals, locals, fromlist, level)

    module.__dict__["__builtins__"] = dict(vars(builtins), __import__=isolated_import, **overrides)
    spec.loader.exec_module(module)
    return module


class BoardProfileTests(unittest.TestCase):
    def profile(self, marker=None, storage=None):
        def open_marker(name):
            if name == "openbuddy-board.txt" and marker is not None:
                return io.StringIO(marker)
            if name == "openbuddy-storage.txt" and storage is not None:
                return io.StringIO(storage)
            raise OSError("no marker")

        opener = Mock(side_effect=open_marker)
        cfg = load_module("board_config", open=opener)
        self.assertEqual(opener.call_args_list[0], call("openbuddy-board.txt"))
        return cfg

    def test_missing_marker_keeps_c6_default_even_on_an_s3(self):
        machine = types.SimpleNamespace(unique_id=lambda: b"esp32-s3")
        cfg = load_module("board_config", {"machine": machine},
                          open=Mock(side_effect=OSError("no marker")))
        self.assertEqual(cfg.BOARD_MODEL, "waveshare-c6-lcd-147")
        self.assertEqual(cfg.DISPLAY_DRIVER, "st7789")
        self.assertEqual((cfg.LCD_SPI_ID, cfg.LCD_SCLK, cfg.LCD_MOSI,
                          cfg.LCD_CS, cfg.LCD_DC, cfg.LCD_RST, cfg.LCD_BL),
                         (1, 7, 6, 14, 15, 21, 22))
        self.assertEqual((cfg.SD_SPI_ID, cfg.SD_SCLK, cfg.SD_MOSI, cfg.SD_MISO, cfg.SD_CS),
                         (1, 7, 6, 5, 4))
        self.assertEqual((cfg.RGB_LED, cfg.BOOT_BUTTON), (8, 9))
        self.assertEqual((cfg.PANEL_SHORT, cfg.PANEL_LONG, cfg.RAM_SHORT_OFFSET), (172, 320, 34))
        self.assertEqual((cfg.UI_WIDTH, cfg.UI_HEIGHT, cfg.UI_PET_SCALE, cfg.UI_PET_STAGE),
                         (320, 172, 1, (8, 35, 104, 104)))
        self.assertEqual(cfg.UI_BACKGROUND, (0, 0, 0))
        self.assertEqual(cfg.UI_DIVIDER_INSET, 0)

    def test_explicit_s3_marker_selects_amoled_and_separate_sd_pins_without_led(self):
        cfg = self.profile("  waveshare-s3-amoled-164-v2\n")
        self.assertEqual(cfg.BOARD_MODEL, "waveshare-s3-amoled-164-v2")
        self.assertEqual(cfg.DISPLAY_DRIVER, "co5300")
        self.assertEqual((cfg.LCD_SPI_ID, cfg.LCD_SCLK, cfg.LCD_MOSI, cfg.LCD_CS, cfg.LCD_RST),
                          (1, 10, 11, 46, 21))
        self.assertEqual(cfg.LCD_SPI_BAUD, 40_000_000)
        self.assertEqual((cfg.SD_SPI_ID, cfg.SD_SCLK, cfg.SD_MOSI, cfg.SD_MISO, cfg.SD_CS),
                         (2, 41, 39, 40, 38))
        self.assertIsNone(cfg.LCD_DC)
        self.assertIsNone(cfg.LCD_BL)
        self.assertIsNone(cfg.RGB_LED)
        self.assertEqual(cfg.BOOT_BUTTON, 0)
        self.assertEqual((cfg.PANEL_SHORT, cfg.PANEL_LONG, cfg.RAM_SHORT_OFFSET), (280, 456, 20))
        self.assertEqual((cfg.UI_WIDTH, cfg.UI_HEIGHT, cfg.UI_PET_SCALE, cfg.UI_PET_STAGE),
                         (456, 280, 2, (8, 36, 208, 208)))
        self.assertEqual(cfg.UI_BACKGROUND, (0, 0, 0))
        self.assertEqual(cfg.UI_DIVIDER_INSET, 0)

    def test_explicit_c6_marker_and_unknown_profiles(self):
        cfg = self.profile("waveshare-c6-lcd-147\n")
        self.assertEqual(cfg.DISPLAY_DRIVER, "st7789")
        for marker in ("esp32-s3", "waveshare-s3", "", "unknown", "unsupported-s3"):
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, "Unknown"):
                self.profile(marker)

    def test_v2_defaults_to_internal_storage_without_probing_sd(self):
        cfg = self.profile("waveshare-s3-amoled-164-v2\n")
        self.assertEqual((cfg.DISPLAY_DRIVER, cfg.LCD_CS, cfg.LCD_SPI_BAUD),
                         ("co5300", 46, 40_000_000))
        self.assertEqual(cfg.PET_STORAGE, "internal")
        self.assertEqual((cfg.PET_DIRECTORY, cfg.PET_SELECTION),
                          ("/openbuddy/pets", "/openbuddy/active.json"))

    def test_v2_reads_only_a_valid_bounded_storage_preference(self):
        cfg = self.profile("waveshare-s3-amoled-164-v2", "sd")
        self.assertEqual(cfg.PET_STORAGE, "sd")
        self.assertEqual((cfg.PET_DIRECTORY, cfg.PET_SELECTION),
                         ("/sd/openbuddy/pets", "/sd/openbuddy/active.json"))
        for value in ("", "unknown", "sd" + "x" * 32):
            with self.subTest(value=value):
                self.assertEqual(self.profile("waveshare-s3-amoled-164-v2", value).PET_STORAGE,
                                 "internal")
        self.assertEqual(self.profile("waveshare-c6-lcd-147", "sd").PET_STORAGE, "auto")

    def test_frozen_build_default_is_used_only_without_saved_marker(self):
        build = types.SimpleNamespace(BOARD_MODEL="waveshare-s3-amoled-164-v2")
        cfg = load_module("board_config", {"openbuddy_build": build},
                          open=Mock(side_effect=OSError("no marker")))
        self.assertEqual((cfg.BOARD_MODEL, cfg.LCD_CS), (build.BOARD_MODEL, 46))
        cfg = load_module("board_config", {"openbuddy_build": build},
                          open=Mock(return_value=io.StringIO("waveshare-c6-lcd-147")))
        self.assertEqual((cfg.BOARD_MODEL, cfg.LCD_CS), ("waveshare-c6-lcd-147", 14))

    def test_sd_only_bus_uses_s3_sd_controller_without_reconfiguring_lcd_bus(self):
        cfg = self.profile("waveshare-s3-amoled-164-v2")
        machine = types.SimpleNamespace(Pin=Mock(OUT=1), SPI=Mock())
        shared = load_module("shared_spi", {"machine": machine, "board_config": cfg})
        bus = shared.SharedSPI(sd_only=True)
        machine.SPI.assert_called_once_with(
            2, baudrate=8_000_000, polarity=0, phase=0,
            sck=machine.Pin.return_value, mosi=machine.Pin.return_value,
            miso=machine.Pin.return_value)
        self.assertEqual(machine.Pin.call_args_list, [
            call(38, machine.Pin.OUT, value=1),
            call(41), call(39), call(40),
        ])
        self.assertIsNone(bus.lcd_cs)
        bus.for_lcd()
        bus.spi.init.assert_not_called()
        self.assertEqual(bus.baudrate, 8_000_000)


class StorageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_module("board_config", open=Mock(side_effect=OSError("no marker")))
        self.player_factory = Mock()
        self.bus_factory = Mock(return_value=Mock())
        self.card_factory = Mock(return_value=types.SimpleNamespace(sectors=8))
        self.vfs = types.SimpleNamespace(mount=Mock(), umount=Mock())
        self.clock = types.SimpleNamespace(sleep_ms=Mock())
        self.storage_module = load_module("storage", {
            "board_config": self.cfg,
            "pet_player": types.SimpleNamespace(PetPlayer=self.player_factory),
            "sdcard_spi": types.SimpleNamespace(ReadOnlySDCard=self.card_factory),
            "shared_spi": types.SimpleNamespace(SharedSPI=self.bus_factory),
            "vfs": self.vfs, "time": self.clock,
        }, print=Mock())
        self.storage = self.storage_module.Storage(None)
        self.lcd = object()

    def player(self, available):
        return types.SimpleNamespace(available=available, close=Mock())

    def assert_player_paths(self, *roots):
        self.assertEqual(self.player_factory.call_args_list, [
            call(self.lcd, directory=root + "/pets", selection=root + "/active.json")
            for root in roots
        ])

    def test_valid_internal_pack_never_mounts_or_creates_an_spi_bus(self):
        internal = self.player(True)
        self.player_factory.return_value = internal
        self.storage.mount = Mock(side_effect=AssertionError("internal pack must not mount SD"))
        self.assertIs(self.storage.load_player(self.lcd), internal)
        self.assertEqual(internal.source, "internal")
        self.assert_player_paths("/openbuddy")
        internal.close.assert_not_called()
        self.storage.mount.assert_not_called()
        self.bus_factory.assert_not_called()
        self.card_factory.assert_not_called()
        self.vfs.mount.assert_not_called()
        self.assertIsNone(self.storage.bus)
        self.assertFalse(self.storage.mounted)

    def test_internal_only_profile_never_probes_sd_even_if_pack_is_missing(self):
        self.cfg.PET_STORAGE = "internal"
        internal = self.player(False)
        self.player_factory.return_value = internal
        self.assertIsNone(self.storage.load_player(self.lcd))
        self.assertIsNone(self.storage.load_player(self.lcd, attempts=1))
        self.assertFalse(self.storage.mount())
        self.assert_player_paths("/openbuddy", "/openbuddy")
        self.assertEqual(internal.close.call_count, 2)
        self.bus_factory.assert_not_called()
        self.card_factory.assert_not_called()
        self.vfs.mount.assert_not_called()

    def test_s3_sd_preference_reads_only_tf_and_retries_when_it_is_missing(self):
        self.cfg.PET_STORAGE = "sd"
        self.vfs.mount.side_effect = OSError("missing TF")
        self.assertIsNone(self.storage.load_player(self.lcd, attempts=1))
        self.assert_player_paths()
        self.bus_factory.assert_called_once_with(sd_only=True)
        self.assertFalse(self.storage.mounted)
        self.vfs.mount.side_effect = None
        sd = self.player(True)
        self.player_factory.return_value = sd
        self.assertIs(self.storage.load_player(self.lcd, attempts=1), sd)
        self.assertEqual(sd.source, "sd")
        self.assert_player_paths("/sd/openbuddy")
        self.assertTrue(self.storage.mounted)

    def test_invalid_internal_pack_is_closed_before_readonly_sd_fallback(self):
        internal, sd = self.player(False), self.player(True)
        self.player_factory.side_effect = [internal, sd]
        events = Mock()
        events.attach_mock(internal.close, "close_internal")
        events.attach_mock(self.bus_factory, "create_bus")
        events.attach_mock(self.card_factory, "create_card")
        events.attach_mock(self.vfs.mount, "mount")
        self.assertIs(self.storage.load_player(self.lcd, attempts=1), sd)
        self.assertEqual(sd.source, "sd")
        self.assert_player_paths("/openbuddy", "/sd/openbuddy")
        self.assertEqual(events.mock_calls[:2], [call.close_internal(), call.create_bus(sd_only=True)])
        self.card_factory.assert_called_once_with(self.storage.bus, 8_000_000)
        self.vfs.mount.assert_called_once_with(self.card_factory.return_value, "/sd", readonly=True)
        self.storage.bus.for_lcd.assert_called_once_with()
        self.assertTrue(self.storage.mounted)
        sd.close.assert_not_called()

    def test_mount_failure_returns_no_player_and_does_not_probe_sd_pack(self):
        internal = self.player(False)
        self.player_factory.return_value = internal
        self.vfs.mount.side_effect = OSError("missing SD")
        self.assertIsNone(self.storage.load_player(self.lcd, attempts=2))
        self.assert_player_paths("/openbuddy")
        internal.close.assert_called_once_with()
        self.bus_factory.assert_called_once_with(sd_only=True)
        self.assertEqual(self.vfs.mount.call_count, 2)
        self.clock.sleep_ms.assert_called_once_with(400)
        self.assertEqual(self.storage.bus.for_lcd.call_count, 2)
        self.assertFalse(self.storage.mounted)
        self.assertIsNone(self.storage.card)
        self.assertEqual(self.storage.error, "missing SD")

    def test_invalid_sd_pack_is_closed_and_returns_no_player(self):
        internal, sd = self.player(False), self.player(False)
        self.player_factory.side_effect = [internal, sd]
        self.assertIsNone(self.storage.load_player(self.lcd))
        self.assert_player_paths("/openbuddy", "/sd/openbuddy")
        internal.close.assert_called_once_with()
        sd.close.assert_called_once_with()

    def test_already_mounted_sd_is_reused_without_mount_or_new_bus(self):
        self.storage.mounted = True
        self.storage.mount = Mock(side_effect=AssertionError("SD is already mounted"))
        internal, sd = self.player(False), self.player(True)
        self.player_factory.side_effect = [internal, sd]
        self.assertIs(self.storage.load_player(self.lcd, attempts=1), sd)
        self.storage.mount.assert_not_called()
        self.bus_factory.assert_not_called()
        self.assertEqual(sd.source, "sd")

    def test_reload_after_internal_player_is_disabled_falls_back_to_sd(self):
        original, disabled, sd = self.player(True), self.player(False), self.player(True)
        self.player_factory.side_effect = [original, disabled, sd]
        player = self.storage.load_player(self.lcd)
        self.assertIs(player, original)
        self.bus_factory.assert_not_called()
        # Match the companion reload path after a read error disables the player.
        player.available = False
        player.close()
        player = self.storage.load_player(self.lcd, attempts=1)
        self.assertIs(player, sd)
        self.assertEqual(player.source, "sd")
        original.close.assert_called_once_with()
        disabled.close.assert_called_once_with()
        self.assert_player_paths("/openbuddy", "/openbuddy", "/sd/openbuddy")
        self.bus_factory.assert_called_once_with(sd_only=True)
        self.vfs.mount.assert_called_once()


if __name__ == "__main__":
    unittest.main()
