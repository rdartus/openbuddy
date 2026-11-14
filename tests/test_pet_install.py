import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pc import pet


ROOT = Path(__file__).resolve().parents[1]
PREPARE = compile((ROOT / "tools/prepare_pet_sd.py").read_text(), "prepare_pet_sd.py", "exec")
VERIFY = compile((ROOT / "tools/verify_pet_sd.py").read_text(), "verify_pet_sd.py", "exec")


class Device:
    """Run the actual RAM scripts against an isolated filesystem and hardware mocks."""

    def __init__(self, root, model="s3-amoled", driver="co5300", free=8 * 1024 * 1024):
        self.root = root
        self.cwd = "/"
        self.free = {"/": free, "/sd": 8 * 1024 * 1024}
        self.cfg = SimpleNamespace(DISPLAY_DRIVER=driver, LCD_CS=14, SD_CS=4,
                                   LCD_SPI_ID=1, LCD_SCLK=7, LCD_MOSI=6,
                                   SD_MISO=5, SD_MOUNT="/sd")
        if model is not None:
            self.cfg.BOARD_MODEL = model
        self.machine = SimpleNamespace(Pin=Mock(OUT=1), SPI=Mock(), SDCard=Mock())
        self.vfs = SimpleNamespace(mount=Mock(), umount=Mock())
        self.os = SimpleNamespace(stat=Mock(side_effect=lambda path: self.path(path).stat()),
                                  statvfs=Mock(side_effect=self.statvfs),
                                  mkdir=Mock(side_effect=lambda path: self.path(path).mkdir()),
                                  chdir=Mock(side_effect=self.chdir), sync=Mock(),
                                  rename=Mock(side_effect=lambda a, b: self.path(a).rename(self.path(b))))
        self.env = {"PACK_ID": "test-pet", "REPLACE": False, "STORAGE": "auto",
                    "PACK_SIZES": [20000, 1000], "open": self.open}
        self.output = io.StringIO()
        (root / "sd").mkdir()

    def path(self, path):
        if not path.startswith("/"):
            path = self.cwd.rstrip("/") + "/" + path
        return self.root / path.lstrip("/")

    def chdir(self, path):
        if not self.path(path).is_dir():
            raise OSError(2, "Missing directory")
        self.cwd = path

    def open(self, path, *args, **kwargs):
        return self.path(path).open(*args, **kwargs)

    def statvfs(self, path):
        # Deliberately report more f_bfree than f_bavail.
        return (4096, 4096, 99999, 99999, self.free[path] // 4096, 0, 0, 0, 0, 255)

    def run(self, code):
        with patch.dict(sys.modules, {"os": self.os, "board_config": self.cfg,
                                      "vfs": self.vfs, "machine": self.machine}):
            with contextlib.redirect_stdout(self.output):
                exec(code, self.env)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.device = Device(self.root)

    def make_pack(self):
        folder = self.device.root / "host"
        folder.mkdir()
        data = b"\xf8\x00" * 10000
        (folder / "idle.rgb565").write_bytes(data)
        manifest = {"version": 1, "id": "test-pet", "format": "RGB565-BE",
                    "animations": {"idle": {"file": "idle.rgb565", "bytes": len(data),
                                              "sha256": hashlib.sha256(data).hexdigest()}}}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        return folder

    def transfer(self):
        folder = self.make_pack()
        self.device.env["PACK_SIZES"] = [(folder / name).stat().st_size
                                          for name in ("idle.rgb565", "manifest.json")]
        self.device.env["MANIFEST_SHA256"] = hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest()
        self.device.run(PREPARE)
        for name in ("idle.rgb565", "manifest.json"):
            self.device.path(name).write_bytes((folder / name).read_bytes())
        return folder

    def test_auto_internal_never_touches_sd_hardware_or_paths(self):
        # Internal installation must not even need SD pin definitions or imports.
        self.device.cfg = SimpleNamespace(BOARD_MODEL="s3-amoled", DISPLAY_DRIVER="co5300")
        with patch.dict(sys.modules, {"machine": None, "vfs": None}):
            self.device.run(PREPARE)
        self.assertEqual(self.device.env["ASSET_ROOT"], "/openbuddy")
        self.assertEqual(self.device.cwd, "/openbuddy/pets/test-pet")
        self.device.machine.Pin.assert_not_called()
        self.device.vfs.mount.assert_not_called()
        for method in (self.device.os.stat, self.device.os.statvfs, self.device.os.mkdir):
            self.assertTrue(all(not call.args[0].startswith("/sd") for call in method.call_args_list))
        self.assertIn("free 8388608 required", self.device.output.getvalue())
        self.assertIn("Selected storage: internal", self.device.output.getvalue())

    def test_auto_legacy_and_other_displays_select_sd(self):
        for model, driver in ((None, "co5300"), ("C6", "co5300"),
                              ("esp32-c6-lcd-1.47", "st7789"), ("s3", "st7789")):
            with self.subTest(model=model, driver=driver), tempfile.TemporaryDirectory() as temporary:
                device = Device(Path(temporary), model=model, driver=driver)
                device.run(PREPARE)
                self.assertEqual(device.env["ASSET_ROOT"], "/sd/openbuddy")
                device.vfs.mount.assert_called_once()
                self.assertEqual(device.cwd, "/sd/openbuddy/pets/test-pet")

    def test_explicit_internal_works_on_legacy_c6(self):
        del self.device.cfg.BOARD_MODEL
        self.device.env["STORAGE"] = "internal"
        self.device.run(PREPARE)
        self.assertEqual(self.device.env["SELECTED_STORAGE"], "internal")
        self.device.vfs.mount.assert_not_called()

    def test_explicit_sd_overrides_internal_preference_and_respects_mount(self):
        self.device.cfg.SD_MOUNT = "/card"
        self.device.free["/card"] = self.device.free["/sd"]
        (self.root / "card").mkdir()
        self.device.env["STORAGE"] = "sd"
        self.device.run(PREPARE)
        self.assertEqual(self.device.env["ASSET_ROOT"], "/card/openbuddy")
        self.device.vfs.mount.assert_called_once_with(self.device.machine.SDCard.return_value, "/card")

    def test_auto_insufficient_flash_falls_back_to_sd(self):
        self.device.free["/"] = 256 * 1024
        self.device.run(PREPARE)
        self.assertEqual(self.device.env["SELECTED_STORAGE"], "sd")
        self.assertFalse((self.root / "openbuddy").exists())
        self.assertIn("falling back to SD", self.device.output.getvalue())

    def test_v2_auto_uses_internal_without_sd_fallback(self):
        self.device.cfg.PET_STORAGE = "internal"
        self.device.run(PREPARE)
        self.assertEqual(self.device.env["SELECTED_STORAGE"], "internal")
        self.device.machine.Pin.assert_not_called()
        self.device.vfs.mount.assert_not_called()

    def test_v2_insufficient_flash_or_explicit_sd_fails_before_hardware_and_writes(self):
        for storage, free, message in (("auto", 0, "Insufficient internal flash"),
                                       ("sd", 8 * 1024 * 1024, "requires internal flash")):
            with self.subTest(storage=storage):
                self.device.cfg.PET_STORAGE = "internal"
                self.device.env["STORAGE"] = storage
                self.device.free["/"] = free
                with self.assertRaisesRegex(ValueError, message):
                    self.device.run(PREPARE)
        self.device.os.mkdir.assert_not_called()
        self.device.machine.Pin.assert_not_called()
        self.device.vfs.mount.assert_not_called()

    def test_s3_sd_uses_separate_pins_and_native_slot_two(self):
        self.device.cfg.SD_SPI_ID = 2
        self.device.cfg.SD_SCLK = 41
        self.device.cfg.SD_MOSI = 39
        self.device.cfg.SD_MISO = 40
        self.device.cfg.SD_CS = 38
        self.device.env["STORAGE"] = "sd"
        self.device.run(PREPARE)
        self.assertEqual(self.device.machine.SPI.call_args.args, (2,))
        self.device.machine.SPI.return_value.deinit.assert_called_once()
        self.assertEqual(self.device.machine.SDCard.call_args.kwargs["slot"], 2)
        pin_numbers = [call.args[0] for call in self.device.machine.Pin.call_args_list]
        self.assertIn(41, pin_numbers)
        self.assertIn(39, pin_numbers)
        self.assertNotIn(10, pin_numbers)
        self.assertNotIn(11, pin_numbers)

    def test_auto_insufficient_flash_without_sd_fails_before_writes(self):
        self.device.free["/"] = 0
        self.device.machine.SDCard.side_effect = OSError("no card")
        with self.assertRaisesRegex(ValueError, "SD unavailable.*auto.*no card"):
            self.device.run(PREPARE)
        self.device.os.mkdir.assert_not_called()

    def test_explicit_internal_insufficient_f_bavail_never_uses_sd(self):
        self.device.env["STORAGE"] = "internal"
        self.device.free["/"] = 256 * 1024
        with self.assertRaisesRegex(ValueError, "Insufficient internal flash.*256 KiB"):
            self.device.run(PREPARE)
        self.device.vfs.mount.assert_not_called()
        self.device.os.mkdir.assert_not_called()

    def test_insufficient_sd_fails_before_writes(self):
        self.device.env["STORAGE"] = "sd"
        self.device.free["/sd"] = 0
        with self.assertRaisesRegex(ValueError, "Insufficient SD space"):
            self.device.run(PREPARE)
        self.device.os.mkdir.assert_not_called()

    def test_capacity_includes_rounding_metadata_and_reserve(self):
        block = 4096
        required = 256 * 1024 + 6 * block + 10 * block
        self.device.free["/"] = required
        self.device.env["STORAGE"] = "internal"
        self.device.run(PREPARE)
        self.assertIn("required %d" % required, self.device.output.getvalue())

    def test_replacement_requires_known_bounded_metadata_and_no_reclaim(self):
        self.device.run(PREPARE)
        marker = self.device.path("openbuddy-install.json")
        self.device.cwd = "/"
        with self.assertRaisesRegex(ValueError, "explicitly allow replacement"):
            self.device.run(PREPARE)
        self.device.env["REPLACE"] = True
        self.device.run(PREPARE)  # interrupted installs are recognized by their marker
        self.device.cwd = "/"
        marker.write_text(json.dumps({"id": "other", "format": "RGB565-BE"}))
        with self.assertRaisesRegex(ValueError, "not this OpenBuddy pack"):
            self.device.run(PREPARE)
        marker.write_text("x" * 257)
        with self.assertRaisesRegex(ValueError, "marker too large"):
            self.device.run(PREPARE)
        self.device.free["/"] = 0
        self.device.env["STORAGE"] = "internal"
        with self.assertRaisesRegex(ValueError, "Insufficient internal"):
            self.device.run(PREPARE)
        self.assertEqual(marker.read_text(), "x" * 257)

    def test_verify_internal_and_sd_activate_only_after_hashes(self):
        for storage in ("internal", "sd"):
            with self.subTest(storage=storage), tempfile.TemporaryDirectory() as temporary:
                device = Device(Path(temporary))
                device.env["STORAGE"] = storage
                original = self.device
                self.device = device
                try:
                    self.transfer()
                finally:
                    self.device = original
                device.run(VERIFY)
                selection = device.path(device.env["ASSET_ROOT"] + "/active.json")
                self.assertEqual(json.loads(selection.read_text()), {"pet": "test-pet"})
                self.assertIn("Verified: idle.rgb565", device.output.getvalue())
                self.assertEqual(device.cwd, "/")
                self.assertEqual(device.vfs.umount.call_count, int(storage == "sd"))
                self.assertEqual(device.machine.SDCard.return_value.deinit.call_count, int(storage == "sd"))

    def test_bad_transferred_hash_or_size_never_changes_selection(self):
        self.transfer()
        selection = self.device.path("/openbuddy/active.json")
        selection.write_text('{"pet":"previous"}')
        for data, error in ((b"x" * 20000, "checksum mismatch"), (b"x", "size mismatch")):
            self.device.path("idle.rgb565").write_bytes(data)
            with self.assertRaisesRegex(ValueError, error):
                self.device.run(VERIFY)
            self.assertEqual(json.loads(selection.read_text()), {"pet": "previous"})
        self.device.vfs.umount.assert_not_called()

    def test_changed_manifest_is_rejected_before_activation(self):
        self.transfer()
        self.device.path("manifest.json").write_text('{"id":"other"}')
        with self.assertRaisesRegex(ValueError, "manifest checksum mismatch"):
            self.device.run(VERIFY)
        self.assertFalse(self.device.path("/openbuddy/active.json").exists())

    def test_host_single_chain_uses_remote_cwd_and_runs_real_workflow(self):
        folder = self.make_pack()

        def mpremote(command, **kwargs):
            if command[-1] == "reset":
                return
            exec(command[command.index("exec") + 1], self.device.env)
            self.device.run(PREPARE)
            for index, value in enumerate(command):
                if value == "cp":
                    source, destination = command[index + 1:index + 3]
                    self.assertEqual(destination, ":" + Path(source).name)
                    self.device.path(destination[1:]).write_bytes(Path(source).read_bytes())
            self.device.run(VERIFY)

        args = SimpleNamespace(pack=str(folder), port="auto", storage="auto", replace=False)
        with patch.object(pet.subprocess, "run", side_effect=mpremote) as run:
            pet.install(args)
        command = run.call_args_list[0].args[0]
        self.assertEqual(command[4:6], ["connect", "auto"])
        self.assertEqual(command[-2:], ["run", str(ROOT / "tools/verify_pet_sd.py")])
        self.assertEqual(self.device.env["PACK_SIZES"], [20000, (folder / "manifest.json").stat().st_size])
        self.assertEqual(run.call_args_list[-1].args[0][-1], "reset")
        self.assertTrue(self.device.path("/openbuddy/active.json").is_file())

    def test_host_resets_after_transfer_failure(self):
        folder = self.make_pack()
        args = SimpleNamespace(pack=str(folder), port="auto", storage="sd", replace=True)
        with patch.object(pet.subprocess, "run", side_effect=[subprocess.CalledProcessError(1, "mpremote"), None]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                pet.install(args)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][-1], "reset")

    def test_mpremote_copy_preserves_remote_cwd_and_installer_globals(self):
        try:
            from mpremote.commands import do_filesystem_cp
            from mpremote.transport import Transport
        except ImportError:
            self.skipTest("Optional mpremote dependency is not installed")
        folder = self.make_pack()
        device = self.device

        class RamTransport(Transport):
            def exec(self, source):
                device.run(compile(source, "mpremote", "exec"))

            def eval(self, source):
                return eval(source, device.env)

        device.env["PACK_SIZES"] = [20000, (folder / "manifest.json").stat().st_size]
        device.env["MANIFEST_SHA256"] = hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest()
        device.run(PREPARE)
        state = SimpleNamespace(transport=RamTransport())
        for name in ("idle.rgb565", "manifest.json"):
            do_filesystem_cp(state, str(folder / name), ":" + name, False, check_hash=True)
        device.run(VERIFY)
        self.assertTrue(device.path("/openbuddy/active.json").exists())

    def test_untrusted_ids_and_pack_sizes_fail_before_hardware_or_writes(self):
        for changes in ({"PACK_ID": "../escape"}, {"PACK_ID": "-invalid"},
                        {"PACK_SIZES": []}, {"PACK_SIZES": [0, 100]},
                        {"PACK_SIZES": [20000, 8193]}, {"PACK_SIZES": [True, 100]},
                        {"STORAGE": "unknown"}):
            with self.subTest(changes=changes):
                original = self.device.env.copy()
                self.device.env.update(changes)
                with self.assertRaises(ValueError):
                    self.device.run(PREPARE)
                self.device.env = original
        self.device.os.mkdir.assert_not_called()
        self.device.machine.Pin.assert_not_called()

    def test_host_rejects_bad_checksum_before_contacting_hardware(self):
        folder = self.make_pack()
        (folder / "idle.rgb565").write_bytes(b"x" * 20000)
        with patch.object(pet.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                pet.install(SimpleNamespace(pack=str(folder)))
        run.assert_not_called()

    def test_cli_retains_conversion_defaults_and_adds_auto_install_defaults(self):
        with patch.object(sys, "argv", ["pet", "install", "pack"]), patch.object(pet, "install") as install:
            pet.main()
        args = install.call_args.args[0]
        self.assertEqual((args.port, args.storage, args.replace), ("auto", "auto", False))
        with patch.object(sys, "argv", ["pet", "convert"]), patch.object(pet, "convert_command") as convert:
            pet.main()
        self.assertEqual(convert.call_args.args[0].pet, pet.DEFAULT_PET)


if __name__ == "__main__":
    unittest.main()
