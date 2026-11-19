import io
import types
import unittest
from unittest.mock import MagicMock, Mock

from test_amoled import board_file, load_module


class Clock:
    def __init__(self):
        self.now = 0
        self.limit = None

    def ticks_ms(self):
        return self.now

    @staticmethod
    def ticks_add(now, delta):
        return (now + delta) % (1 << 30)

    @staticmethod
    def ticks_diff(a, b):
        period = 1 << 30
        return (a - b + period // 2) % period - period // 2

    def sleep_ms(self, delta):
        self.now += delta
        if self.limit is not None and self.now >= self.limit:
            raise KeyboardInterrupt


def config(board="waveshare-s3-amoled-164-v2"):
    return load_module("board_config", open=board_file(board))


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.i2c = Mock()
        self.registers = {0: b"\x05", 0x2E: b"\x01", 0x35: b"\0\x40\0\xc0\xff\xff"}

        def read(address, register, target):
            self.assertEqual(address, 0x6B)
            target[:] = self.registers[register]

        self.i2c.readfrom_mem_into.side_effect = read
        self.machine = types.SimpleNamespace(Pin=Mock(side_effect=lambda pin: pin),
                                             I2C=Mock(return_value=self.i2c))
        self.module = load_module("qmi8658", {"machine": self.machine, "board_config": self.cfg})

    def test_vendor_pins_identity_accelerometer_only_and_little_endian(self):
        sensor = self.module.Accelerometer()
        self.machine.I2C.assert_called_once_with(0, sda=47, scl=48, freq=300000, timeout=10000)
        self.assertEqual([call.args for call in self.i2c.writeto_mem.call_args_list], [
            (0x6B, 8, b"\0"), (0x6B, 2, b"\x60"), (0x6B, 3, b"\x07"),
            (0x6B, 6, b"\0"), (0x6B, 9, b"\0"), (0x6B, 8, b"\x01")])
        buffer = sensor.buffer
        self.assertEqual(sensor.read(), (16384, -16384, -1))
        self.assertIs(sensor.buffer, buffer)
        self.registers[0x2E] = b"\x02"  # Gyro-only ready is not an accelerometer sample.
        self.i2c.readfrom_mem_into.reset_mock()
        self.assertIsNone(sensor.read())
        self.assertEqual(self.i2c.readfrom_mem_into.call_count, 1)
        sensor.close()
        sensor.close()
        self.i2c.deinit.assert_called_once()

    def test_wrong_identity_or_configuration_failure_releases_bus(self):
        self.registers[0] = b"\x00"
        with self.assertRaisesRegex(ValueError, "WHO_AM_I"):
            self.module.Accelerometer()
        self.i2c.writeto_mem.assert_not_called()
        self.i2c.deinit.assert_called_once()
        self.i2c.reset_mock()
        self.registers[0] = b"\x05"
        self.i2c.writeto_mem.side_effect = OSError("I2C unavailable")
        with self.assertRaises(OSError):
            self.module.Accelerometer()
        self.i2c.deinit.assert_called_once()

    def test_only_v2_enables_imu(self):
        for model in ("waveshare-c6-lcd-147",):
            cfg = config(model)
            self.assertFalse(cfg.AUTO_ORIENTATION)
            self.assertFalse(hasattr(cfg, "IMU_SDA"))
        self.assertTrue(self.cfg.AUTO_ORIENTATION)


class OrientationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.clock = Clock()
        self.module = load_module("buddy_orientation", {"board_config": self.cfg, "time": self.clock})
        self.sensor = Mock()
        self.sensor.read.return_value = (0, 16384, 0)
        self.factory = Mock(return_value=self.sensor)
        self.auto = self.module.AutoOrientation(self.factory)

    def test_landscape_polarity_and_ignored_positions(self):
        for sample, expected in (((0, 16384, 0), "landscape"), ((0, -16384, 0), "landscape_inv"),
                                 ((-1240, 16145, -2059), "landscape"),
                                 ((1232, -16047, -4340), "landscape_inv")):
            self.assertEqual(self.module.gravity_orientation(sample), expected)
        for sample in ((0, 0, 16384), (0, 0, -16384), (0, 0, 0), (30000, 0, 0),
                        (11585, 11585, 0), (12000, 0, 12000), (1000, 500, 300),
                        (-32768, 0, 0), (-16384, 0, 0), (16384, 0, 0),
                        (16145, -1240, -2059)):
            with self.subTest(sample=sample):
                self.assertIsNone(self.module.gravity_orientation(sample))

    def test_mounting_axis_and_sign_are_configurable(self):
        self.cfg.IMU_LANDSCAPE_AXIS, self.cfg.IMU_LANDSCAPE_SIGN = 0, 1
        self.assertEqual(self.module.gravity_orientation((-16384, 0, 0)), "landscape")
        self.assertEqual(self.module.gravity_orientation((16384, 0, 0)), "landscape_inv")
        self.assertIsNone(self.module.gravity_orientation((0, 16384, 0)))

    def test_nonblocking_poll_rate_and_half_second_stability(self):
        for now in range(500):
            self.assertIsNone(self.auto.poll(now, "landscape_inv"))
        self.assertEqual(self.sensor.read.call_count, 5)
        self.assertEqual(self.auto.poll(500, "landscape_inv"), "landscape")
        self.assertIsNone(self.auto.poll(600, "landscape"))
        self.factory.assert_called_once()
        self.assertTrue(self.auto.available)

    def test_flat_stale_or_changed_sample_cancels_pending_rotation(self):
        for interruption in (None, (0, 0, 16384), (-16384, 0, 0)):
            with self.subTest(interruption=interruption):
                auto = self.module.AutoOrientation(self.factory)
                self.sensor.read.return_value = (0, 16384, 0)
                auto.poll(0, "landscape_inv")
                self.sensor.read.return_value = interruption
                auto.poll(400, "landscape_inv")
                self.sensor.read.return_value = (0, 16384, 0)
                self.assertIsNone(auto.poll(500, "landscape_inv"))
                self.assertIsNone(auto.poll(900, "landscape_inv"))
                self.assertEqual(auto.poll(1000, "landscape_inv"), "landscape")

    def test_initialization_failure_retries_after_thirty_seconds(self):
        self.factory.side_effect = [OSError("No sensor"), self.sensor]
        self.assertIsNone(self.auto.poll(0, "landscape"))
        self.assertFalse(self.auto.available)
        self.auto.poll(29999, "landscape")
        self.assertEqual(self.factory.call_count, 1)
        self.auto.poll(30000, "landscape")
        self.assertEqual(self.factory.call_count, 2)
        self.assertTrue(self.auto.available)

    def test_three_bus_errors_release_sensor_and_cancel_candidate(self):
        self.auto.poll(0, "landscape_inv")
        self.sensor.read.side_effect = OSError("Read failed")
        for now in (100, 200, 300):
            self.auto.poll(now, "landscape_inv")
        self.assertFalse(self.auto.available)
        self.assertIsNone(self.auto.candidate)
        self.sensor.close.assert_called_once()
        self.sensor.read.side_effect = None
        self.auto.poll(30300, "landscape_inv")
        self.assertTrue(self.auto.available)
        self.assertIsNone(self.auto.poll(30700, "landscape_inv"))
        self.assertEqual(self.auto.poll(30800, "landscape_inv"), "landscape")

    def test_boot_correction_is_not_immediately_undone(self):
        self.auto.poll(0, "landscape")
        self.auto.flip()
        for now in range(100, 1000, 100):
            self.assertIsNone(self.auto.poll(now, "landscape_inv"))
        self.sensor.read.return_value = (0, -16384, 0)
        self.auto.poll(1000, "landscape_inv")
        self.assertEqual(self.auto.poll(1500, "landscape_inv"), "landscape")

    def test_ticks_wraparound(self):
        start = (1 << 30) - 200
        self.auto.poll(start, "landscape_inv")
        self.assertIsNone(self.auto.poll(self.clock.ticks_add(start, 499), "landscape_inv"))
        # The previous read was at 499ms, so the next 100ms polling slot applies.
        self.assertEqual(self.auto.poll(self.clock.ticks_add(start, 599), "landscape_inv"), "landscape")


class CompanionOrientationTests(unittest.TestCase):
    def run_loop(self, model="waveshare-s3-amoled-164-v2", confirm=None, sensor_missing=False):
        cfg = config(model)
        clock = Clock()
        clock.limit = 1600
        lcd = Mock(orientation="landscape")
        lcd.set_orientation.side_effect = lambda name: setattr(lcd, "orientation", name)
        sensor = Mock()
        sensor.read.return_value = (0, -16384, 0)
        factory = Mock(side_effect=OSError("No IMU")) if sensor_missing else Mock(return_value=sensor)
        orientation_module = load_module("buddy_orientation", {"board_config": cfg, "time": clock})
        auto_constructor = Mock(side_effect=lambda: orientation_module.AutoOrientation(factory))
        dependencies = {
            "machine": types.SimpleNamespace(Pin=Mock(IN=0, PULL_UP=2)),
            "board_config": cfg, "time": clock,
            "buddy_orientation": types.SimpleNamespace(FLIP=orientation_module.FLIP,
                                                       AutoOrientation=auto_constructor),
            "co5300": types.SimpleNamespace(LCD=Mock(return_value=lcd)),
            "st7789": types.SimpleNamespace(LCD=Mock(return_value=lcd), rgb=Mock()),
            "buddy_ble": types.SimpleNamespace(BuddyBLE=Mock()),
            "buddy_usb": types.SimpleNamespace(BuddyUSB=Mock()),
            "buddy_ui": types.SimpleNamespace(BuddyUI=Mock()),
            "ft3168": types.SimpleNamespace(Touch=Mock()),
            "shared_spi": types.SimpleNamespace(SharedSPI=Mock()),
            "storage": types.SimpleNamespace(Storage=Mock()),
            "neopixel": types.SimpleNamespace(NeoPixel=MagicMock()),
        }
        dependencies["storage"].Storage.return_value.load_player.return_value = None
        buddy = dependencies["buddy_ble"].BuddyBLE.return_value
        buddy.confirm, buddy.passkey = confirm, None
        buddy.pairing_open.return_value = False
        dependencies["buddy_usb"].BuddyUSB.return_value.online.return_value = True
        # Exercise BOOT after automatic landscape orientation has settled.
        dependencies["machine"].Pin.return_value.value.side_effect = lambda: int(not 800 <= clock.now < 1000)
        firmware = load_module("companion", dependencies)
        firmware.load_orientation = lambda: "landscape"
        firmware.save_orientation = Mock()
        with self.assertRaises(KeyboardInterrupt):
            firmware.run()
        status = dependencies["buddy_ble"].BuddyBLE.call_args.kwargs["asset_status"]
        return firmware, dependencies, lcd, buddy, auto_constructor, status, sensor

    def test_loop_auto_rotation_no_flash_writes_and_manual_landscape_flip(self):
        firmware, deps, lcd, buddy, auto, status, sensor = self.run_loop()
        self.assertEqual([call.args for call in lcd.set_orientation.call_args_list],
                         [("landscape_inv",), ("landscape",)])
        firmware.save_orientation.assert_called_once_with("landscape")
        self.assertEqual(deps["buddy_ui"].BuddyUI.return_value.invalidate.call_count, 2)
        self.assertEqual(status()["orientation"], "landscape")
        # Resources are released by finally, even on Ctrl+C.
        sensor.close.assert_called_once()
        buddy.close.assert_called_once()
        self.assertGreater(buddy.tick.call_count, 20)
        self.assertGreater(deps["buddy_usb"].BuddyUSB.return_value.tick.call_count, 20)

    def test_pairing_confirmation_does_not_flip_display(self):
        firmware, deps, lcd, buddy, auto, status, sensor = self.run_loop(confirm=True)
        buddy.button.assert_called_once_with()
        self.assertEqual([call.args for call in lcd.set_orientation.call_args_list], [("landscape_inv",)])
        firmware.save_orientation.assert_not_called()

    def test_missing_imu_keeps_manual_boot_usb_and_ble_alive(self):
        firmware, deps, lcd, buddy, auto, status, sensor = self.run_loop(sensor_missing=True)
        self.assertEqual([call.args for call in lcd.set_orientation.call_args_list], [("landscape_inv",)])
        self.assertFalse(status()["imu"])
        self.assertGreater(buddy.tick.call_count, 20)

    def test_c6_does_not_instantiate_imu(self):
        firmware, deps, lcd, buddy, auto, status, sensor = self.run_loop("waveshare-c6-lcd-147")
        auto.assert_not_called()
        self.assertEqual(lcd.orientation, "landscape_inv")
        self.assertFalse(status()["imu"])

    def test_saved_orientation_rejects_portrait_even_on_v2(self):
        # Reuse the isolated loader to avoid importing actual machine/BLE modules.
        for model, saved, expected in (("waveshare-s3-amoled-164-v2", "portrait", "landscape"),
                                      ("waveshare-c6-lcd-147", "portrait", "landscape"),
                                      ("waveshare-s3-amoled-164-v2", "invalid", "landscape"),
                                      ("waveshare-s3-amoled-164-v2", "landscape_inv", "landscape_inv")):
            module = load_module("companion", {
                    "machine": types.SimpleNamespace(Pin=Mock()), "board_config": config(model),
                    "buddy_ble": types.SimpleNamespace(BuddyBLE=Mock()),
                    "buddy_usb": types.SimpleNamespace(BuddyUSB=Mock()),
                    "buddy_ui": types.SimpleNamespace(BuddyUI=Mock()),
                    "buddy_orientation": types.SimpleNamespace(
                        FLIP={"landscape": "landscape_inv", "landscape_inv": "landscape"}),
                    "st7789": types.SimpleNamespace(rgb=Mock()),
                    "shared_spi": types.SimpleNamespace(SharedSPI=Mock()),
                    "storage": types.SimpleNamespace(Storage=Mock()),
            }, open=Mock(return_value=io.StringIO(saved)))
            self.assertEqual(module.load_orientation(), expected)


if __name__ == "__main__":
    unittest.main()
