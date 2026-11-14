import hashlib
import json
from pathlib import Path
import tempfile
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
    "native/amoled_qspi/amoled_qspi.c",
    "native/amoled_qspi/micropython.cmake",
}
NATIVE_FILES |= {"native/boards/OPENBUDDY_S3_AMOLED_V2/" + name for name in (
    "mpconfigboard.cmake", "mpconfigboard.h", "sdkconfig.board", "manifest.py", "openbuddy_build.py")}
SOURCE_FILES = {"c6lcd/" + name for name in DEPLOY_FILES} | SUPPORT_FILES | NATIVE_FILES
LICENSES = {
    "licenses/MicroPython-LICENSE.txt": b"MicroPython license fixture\n",
    "licenses/ESP-IDF-LICENSE.txt": b"ESP-IDF license fixture\n",
}
FIRMWARE = b"\xe9\x00mock ESP32-S3 firmware\xff\n"


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
            "CONFIG_SPIRAM_MODE_OCT=y\nCONFIG_ESPTOOLPY_FLASHSIZE_16MB=y\n", encoding="ascii")
        (self.build / "micropython.map").write_text(
            "usermod/amoled_qspi.c.obj\n", encoding="ascii")
        (self.build / "firmware.bin").write_bytes(FIRMWARE)
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
            "qspi_api_version": 2,
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
            self.assertEqual({name for name in names if name.startswith("c6lcd/")},
                             {"c6lcd/" + name for name in DEPLOY_FILES})
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
            "c6lcd/openbuddy-bonds.json", "c6lcd/openbuddy-bonds.json.tmp",
            "c6lcd/extra.py", "c6lcd/__pycache__/main.cpython-313.pyc",
            "pc/bridge.json", "pc/__pycache__/deploy.cpython-313.pyc",
            "docs/hardware-notes.md", "docs/unrelated.md", "docs/media/pet.png",
            "tools/assets/font_petme128_8x8.h", "assets/pet.png",
            "build/pets/example/idle.rgb565", "build/pets/example/manifest.json",
            ".cache/pet.png", ".venv/token", "node_modules/package/index.js",
            "native/amoled_qspi/__pycache__/cache.pyc",
            "native/amoled_qspi/build/amoled_qspi.c.obj",
            "native/amoled_qspi/.env", "native/amoled_qspi/private.key",
            "native/amoled_qspi/amoled_qspi.o",
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
        self.dirty = " M c6lcd/co5300.py"
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


if __name__ == "__main__":
    unittest.main()
