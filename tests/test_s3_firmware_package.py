import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import struct
import unittest
from unittest.mock import call, patch
import zipfile

from pc.deploy import FILES as DEPLOY_FILES
from tools import package_s3_firmware as packager


SUPPORT_FILES = {
    "pc/__init__.py", "pc/deploy.py", "pc/pet.py", "pc/buddy.py",
    "pc/requirements.txt", "pc/requirements-assets.txt",
    "tools/test_amoled.py", "tools/prepare_pet_sd.py", "tools/verify_pet_sd.py",
    "README-ESP32-S3-Windows.md", "docs/s3-qspi-build.md",
    "docs/windows-uv-apres-flash.md", "THIRD_PARTY.md",
}
NATIVE_FILES = {
    "firmware/amoled_qspi/amoled_qspi.c",
    "firmware/amoled_qspi/micropython.cmake",
}
NATIVE_FILES |= {"firmware/boards/OPENBUDDY_S3_AMOLED_V2/" + name for name in (
    "mpconfigboard.cmake", "mpconfigboard.h", "sdkconfig.board", "manifest.py", "openbuddy_build.py")}
SOURCE_FILES = {"device/" + name for name in DEPLOY_FILES} | SUPPORT_FILES | NATIVE_FILES
LICENSES = {
    "licenses/MicroPython-LICENSE.txt": b"MicroPython license fixture\n",
    "licenses/ESP-IDF-LICENSE.txt": b"ESP-IDF license fixture\n",
}
FIRMWARE = b"\xe9\x00mock ESP32-S3 firmware\xff\n"
LINK_MAP = ("usermod/amoled_qspi.c.obj\n"
            "usb_serial_jtag_init\nusb_serial_jtag_poll_rx\nusb_serial_jtag_tx_strn\n")


class S3USBBoardTests(unittest.TestCase):
    def test_release_artifacts_do_not_overlap_firmware_sources(self):
        workflow = (packager.ROOT / ".github/workflows/s3-qspi.yml").read_text(encoding="utf-8")
        self.assertIn("- 'device/**'", workflow)
        self.assertIn("- 'firmware/**'", workflow)
        self.assertIn("path: dist/s3-qspi", workflow)
        self.assertIn('gh release create "$TAG" dist/s3-qspi/*', workflow)
        self.assertNotIn('gh release create "$TAG" device/*', workflow)
        self.assertNotIn('gh release create "$TAG" firmware/*', workflow)

    @unittest.skipUnless(shutil.which("cc"), "A host C preprocessor is not available")
    def test_board_explicitly_keeps_the_hardware_usb_serial_jtag_phy(self):
        header = packager.ROOT / "firmware/boards/OPENBUDDY_S3_AMOLED_V2/mpconfigboard.h"
        probe = """
#if !defined(MICROPY_HW_ENABLE_USBDEV) || !defined(MICROPY_HW_USB_CDC) || !defined(MICROPY_HW_ESP_USB_SERIAL_JTAG)
#error USB backend must not depend on upstream defaults
#endif
#if MICROPY_HW_ENABLE_USBDEV || MICROPY_HW_USB_CDC || !MICROPY_HW_ESP_USB_SERIAL_JTAG
#error The board must keep hardware USB Serial/JTAG, without TinyUSB/OTG
#endif
#if !MICROPY_HW_ENABLE_UART_REPL
#error Keep UART boot diagnostics as well
#endif
"""
        subprocess.run([shutil.which("cc"), "-E", "-P", "-x", "c", "-include", str(header), "-"],
                       input=probe, text=True, capture_output=True, check=True, timeout=10)


class S3FirmwarePackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.micropython = self.temporary / "micropython"
        self.idf = self.temporary / "idf"
        self.build = self.micropython / "ports/esp32/build-OPENBUDDY_S3_AMOLED_V2"
        self.build.mkdir(parents=True)
        self.idf.mkdir()
        (self.build / "sdkconfig").write_text(
            "CONFIG_SPIRAM_MODE_OCT=y\nCONFIG_ESPTOOLPY_FLASHSIZE_16MB=y\n"
            "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED=y\n", encoding="ascii")
        (self.build / "micropython.map").write_text(LINK_MAP, encoding="ascii")
        (self.build / "firmware.bin").write_bytes(FIRMWARE)
        (self.build / "micropython.bin").write_bytes(FIRMWARE)
        (self.build / "partition_table").mkdir()
        entries = [(1, 2, 0x9000, 0x6000, b"nvs"),
                   (1, 1, 0xF000, 0x1000, b"phy_init"),
                   (0, 0, 0x10000, 0x1F0000, b"factory")]
        self.partitions = b"".join(struct.pack("<HBBII16sI", 0x50AA, *entry, 0) for entry in entries)
        (self.build / "partition_table/partition-table.bin").write_bytes(self.partitions + b"\xff" * 32)
        (self.micropython / "LICENSE").write_bytes(LICENSES["licenses/MicroPython-LICENSE.txt"])
        (self.idf / "LICENSE").write_bytes(LICENSES["licenses/ESP-IDF-LICENSE.txt"])
        self.output = self.temporary / "artifacts/s3-qspi"
        self.root = packager.ROOT
        self.dirty = ""
        git_patch = patch.object(packager, "git", side_effect=self.git)
        self.git_mock = git_patch.start()
        self.addCleanup(git_patch.stop)
        stdout_patch = patch("sys.stdout")
        stdout_patch.start()
        self.addCleanup(stdout_patch.stop)

    def git(self, path, *args):
        if path == self.root and args == ("status", "--porcelain", "--untracked-files=normal"):
            return self.dirty
        commits = {self.root: "a" * 40, self.micropython: "b" * 40, self.idf: "c" * 40}
        if path in commits and args == ("rev-parse", "HEAD"):
            return commits[path]
        self.fail("Unexpected git call: %r %r" % (path, args))

    def check_package(self):
        packager.package(self.micropython, self.idf, self.output)
        self.assertEqual({path.name for path in self.output.iterdir()}, {
            "openbuddy-s3-amoled-qspi.bin", "openbuddy-s3-qspi-files.zip",
            "BUILD.json", "INSTALL.md", "SHA256SUMS.txt",
        })
        self.assertEqual((self.output / "openbuddy-s3-amoled-qspi.bin").read_bytes(), FIRMWARE)
        manifest_bytes = (self.output / "BUILD.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest, {
            "board": "waveshare-s3-amoled-164-v2",
            "micropython_board": "OPENBUDDY_S3_AMOLED_V2",
            "flash_bytes": 16 * 1024 * 1024,
            "pet_storage": "internal",
            "lcd_cs": 46,
            "qspi_api_version": 4,
            "orientation_sensor": "qmi8658",
            "usb_backend": "usb-serial-jtag",
            "usb_vid": 0x303A,
            "usb_pid": 0x1001,
            "flash_budget": packager.flash_budget(self.build),
            "experimental": True,
            "openbuddy_commit": "a" * 40,
            "openbuddy_dirty": bool(self.dirty),
            "micropython_version": "v1.29.0",
            "micropython_commit": "b" * 40,
            "esp_idf_version": "v5.5.2",
            "esp_idf_commit": "c" * 40,
            "firmware_sha256": hashlib.sha256(FIRMWARE).hexdigest(),
            "source_files": {
                name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                for name in SOURCE_FILES
            },
        })
        self.assertIs(manifest["openbuddy_dirty"], bool(self.dirty))
        with zipfile.ZipFile(self.output / "openbuddy-s3-qspi-files.zip") as archive:
            names = archive.namelist()
            self.assertEqual(set(names), SOURCE_FILES | set(LICENSES) | {"BUILD.json"})
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual({name for name in names if name.startswith("device/")},
                             {"device/" + name for name in DEPLOY_FILES})
            self.assertEqual(archive.read("BUILD.json"), manifest_bytes)
            for name in SOURCE_FILES:
                with self.subTest(source=name):
                    contents = archive.read(name)
                    self.assertEqual(contents, (self.root / name).read_bytes())
                    self.assertEqual(hashlib.sha256(contents).hexdigest(),
                                     manifest["source_files"][name])
            for name, contents in LICENSES.items():
                self.assertEqual(archive.read(name), contents)
        self.assertEqual((self.output / "INSTALL.md").read_bytes(),
                          (self.root / "README-ESP32-S3-Windows.md").read_bytes())
        checksums = (self.output / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()
        expected_names = ["openbuddy-s3-amoled-qspi.bin", "openbuddy-s3-qspi-files.zip",
                          "BUILD.json", "INSTALL.md"]
        self.assertEqual(checksums, [
            hashlib.sha256((self.output / name).read_bytes()).hexdigest() + "  " + name
            for name in expected_names
        ])
        self.assertEqual(self.git_mock.call_args_list, [
            call(self.root, "rev-parse", "HEAD"),
            call(self.root, "status", "--porcelain", "--untracked-files=normal"),
            call(self.micropython, "rev-parse", "HEAD"),
            call(self.idf, "rev-parse", "HEAD"),
        ])

    def test_full_package_uses_actual_repository_sources_tools_and_docs(self):
        self.check_package()

    def test_allowlist_excludes_secrets_assets_and_caches(self):
        self.root = self.temporary / "sources"
        excluded = {
            ".env", ".env.local", "bridge.json", "openbuddy-bonds.json",
            "device/openbuddy-bonds.json", "device/openbuddy-bonds.json.tmp",
            "device/extra.py", "device/__pycache__/main.cpython-313.pyc",
            "pc/bridge.json", "pc/__pycache__/deploy.cpython-313.pyc",
            "docs/hardware-notes.md", "docs/unrelated.md", "docs/media/pet.png",
            "tools/assets/font_petme128_8x8.h", "assets/pet.png",
            "build/pets/example/idle.rgb565", "build/pets/example/manifest.json",
            ".cache/pet.png", ".venv/token", "node_modules/package/index.js",
            "firmware/amoled_qspi/__pycache__/cache.pyc",
            "firmware/amoled_qspi/build/amoled_qspi.c.obj",
            "firmware/amoled_qspi/.env", "firmware/amoled_qspi/private.key",
            "firmware/amoled_qspi/amoled_qspi.o",
        }
        for name in SOURCE_FILES | excluded:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((name + "\n").encode("ascii"))
        with patch.object(packager, "ROOT", self.root):
            self.check_package()
        with zipfile.ZipFile(self.output / "openbuddy-s3-qspi-files.zip") as archive:
            self.assertTrue(excluded.isdisjoint(archive.namelist()))

    def test_modified_tracked_files_mark_package_dirty(self):
        self.dirty = " M device/co5300.py"
        self.check_package()

    def test_untracked_files_mark_package_dirty(self):
        self.dirty = "?? docs/new-guide.md"
        self.check_package()

    def test_missing_octal_psram_is_rejected_before_outputs_or_git(self):
        (self.build / "sdkconfig").write_text("CONFIG_SPIRAM_MODE_QUAD=y\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "octal PSRAM"):
            packager.package(self.micropython, self.idf, self.output)
        self.assertFalse(self.output.exists())
        self.git_mock.assert_not_called()

    def test_flash_budget_keeps_two_complete_packs_python_and_reserve(self):
        budget = packager.flash_budget(self.build)
        self.assertEqual(budget["app_bytes"], len(FIRMWARE))
        self.assertEqual(budget["app_partition_bytes"], 0x1F0000)
        self.assertEqual(budget["vfs_offset"], 0x200000)
        self.assertEqual(budget["vfs_bytes"], 14 * 1024 * 1024)
        self.assertEqual(budget["pet_pixel_bytes"], 1457664)
        self.assertEqual(budget["pet_budget_bytes"], 1572864)
        self.assertEqual(budget["pack_copies"], 2)
        self.assertEqual(budget["reserve_bytes"], 256 * 1024)
        self.assertEqual(budget["python_bytes"], sum(
            (self.root / "device" / name).stat().st_size for name in DEPLOY_FILES))
        self.assertGreater(budget["python_budget_bytes"], budget["python_bytes"])
        self.assertEqual(budget["required_vfs_bytes"],
                         budget["python_budget_bytes"] + 2 * budget["pet_budget_bytes"] + 256 * 1024)
        self.assertEqual(budget["spare_vfs_bytes"],
                         budget["vfs_bytes"] - budget["required_vfs_bytes"])
        self.assertGreater(budget["spare_vfs_bytes"], 10 * 1024 * 1024)

    def test_changed_partition_layout_is_rejected_before_outputs(self):
        table = self.build / "partition_table/partition-table.bin"
        for data in (b"", self.partitions[:64], self.partitions + struct.pack(
                "<HBBII16sI", 0x50AA, 1, 0x81, 0x200000, 0x200000, b"vfs", 0)):
            with self.subTest(data=data):
                table.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "partition layout"):
                    packager.package(self.micropython, self.idf, self.output)
                self.assertFalse(self.output.exists())

    def test_oversized_application_or_combined_image_is_rejected(self):
        for name, size, message in (("micropython.bin", 0x1F0001, "application exceeds"),
                                     ("firmware.bin", 0x200001, "overlaps")):
            with self.subTest(name=name):
                path = self.build / name
                path.write_bytes(b"\xff" * size)
                with self.assertRaisesRegex(ValueError, message):
                    packager.package(self.micropython, self.idf, self.output)
                self.assertFalse(self.output.exists())
                path.write_bytes(FIRMWARE)

    def test_insufficient_vfs_budget_is_rejected(self):
        original_stat = Path.stat

        def huge_sources(path, *args, **kwargs):
            if path.parent == self.root / "device":
                from types import SimpleNamespace
                return SimpleNamespace(st_size=1024 * 1024)
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", huge_sources):
            with self.assertRaisesRegex(ValueError, "do not fit internal flash"):
                packager.package(self.micropython, self.idf, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_native_module_marker_is_rejected_before_outputs_or_git(self):
        (self.build / "micropython.map").write_text("other_module.c.obj\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "native amoled_qspi module"):
            packager.package(self.micropython, self.idf, self.output)
        self.assertFalse(self.output.exists())
        self.git_mock.assert_not_called()

    def test_incorrect_flash_size_is_rejected_before_outputs_or_git(self):
        (self.build / "sdkconfig").write_text(
            "CONFIG_SPIRAM_MODE_OCT=y\nCONFIG_ESPTOOLPY_FLASHSIZE_4MB=y\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "16 MiB flash"):
            packager.package(self.micropython, self.idf, self.output)
        self.assertFalse(self.output.exists())
        self.git_mock.assert_not_called()

    def test_missing_compiled_usb_serial_jtag_is_rejected_before_outputs(self):
        for symbol in ("usb_serial_jtag_init", "usb_serial_jtag_poll_rx", "usb_serial_jtag_tx_strn"):
            with self.subTest(symbol=symbol):
                (self.build / "micropython.map").write_text(LINK_MAP.replace(symbol, "missing_symbol"))
                with self.assertRaisesRegex(ValueError, "USB Serial/JTAG stdio"):
                    packager.package(self.micropython, self.idf, self.output)
                self.assertFalse(self.output.exists())
                self.git_mock.assert_not_called()

    def test_tinyusb_or_otg_firmware_is_rejected_before_outputs(self):
        for symbol in ("mp_usbd_cdc_tx_strn", "usb_phy_init"):
            with self.subTest(symbol=symbol):
                (self.build / "micropython.map").write_text(LINK_MAP + symbol + "\n")
                with self.assertRaisesRegex(ValueError, "must not switch.*TinyUSB"):
                    packager.package(self.micropython, self.idf, self.output)
                self.assertFalse(self.output.exists())
                self.git_mock.assert_not_called()

    def test_similar_symbol_names_do_not_count_as_compiled_usb_stdio(self):
        (self.build / "micropython.map").write_text(
            LINK_MAP.replace("usb_serial_jtag_init", "usb_serial_jtag_init_other"))
        with self.assertRaisesRegex(ValueError, "USB Serial/JTAG stdio"):
            packager.package(self.micropython, self.idf, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_early_usb_diagnostics_is_rejected_before_outputs(self):
        config = self.build / "sdkconfig"
        config.write_text(config.read_text().replace("CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED=y", ""))
        with self.assertRaisesRegex(ValueError, "boot diagnostics"):
            packager.package(self.micropython, self.idf, self.output)
        self.assertFalse(self.output.exists())
        self.git_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
