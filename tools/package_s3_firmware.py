"""Package native firmware with the exact allowlisted Python deployment and hashes."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BOARD = "OPENBUDDY_S3_AMOLED_V2"
BOARD_FILES = {"native/boards/" + BOARD + "/" + name for name in (
    "mpconfigboard.cmake", "mpconfigboard.h", "sdkconfig.board", "manifest.py", "openbuddy_build.py")}
sys.path.insert(0, str(ROOT))
from pc.deploy import FILES


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def package(micropython, idf, output):
    build = micropython / ("ports/esp32/build-" + BOARD)
    # Never package an arbitrary host-test binary as an ESP32 firmware.
    sdkconfig = (build / "sdkconfig").read_text()
    if "CONFIG_SPIRAM_MODE_OCT=y" not in sdkconfig:
        raise ValueError("The firmware must enable octal PSRAM")
    if "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y" not in sdkconfig:
        raise ValueError("The v2 firmware must target 16 MiB flash")
    if "amoled_qspi.c.obj" not in (build / "micropython.map").read_text():
        raise ValueError("The firmware must link the native amoled_qspi module")
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "openbuddy-s3-amoled-qspi.bin"
    firmware.write_bytes((build / "firmware.bin").read_bytes())
    source_files = {"c6lcd/" + name for name in FILES}
    source_files.update({"pc/__init__.py", "pc/deploy.py", "pc/pet.py", "pc/buddy.py",
                         "pc/requirements.txt", "pc/requirements-assets.txt",
                         "tools/test_amoled.py", "tools/prepare_pet_sd.py", "tools/verify_pet_sd.py",
                         "README-ESP32-S3-Windows.md", "docs/s3-qspi-build.md",
                         "docs/windows-uv-apres-flash.md", "THIRD_PARTY.md"})
    source_files.update({"native/amoled_qspi/amoled_qspi.c",
                         "native/amoled_qspi/micropython.cmake"})
    source_files.update(BOARD_FILES)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in sorted(source_files)}
    manifest = {
        "board": "waveshare-s3-amoled-164-v2", "experimental": True,
        "micropython_board": BOARD, "flash_bytes": 16 * 1024 * 1024,
        "pet_storage": "internal", "lcd_cs": 46, "qspi_api_version": 2,
        "openbuddy_commit": git(ROOT, "rev-parse", "HEAD"),
        "openbuddy_dirty": bool(git(ROOT, "status", "--porcelain", "--untracked-files=normal")),
        "micropython_version": "v1.29.0", "micropython_commit": git(micropython, "rev-parse", "HEAD"),
        "esp_idf_version": "v5.5.2", "esp_idf_commit": git(idf, "rev-parse", "HEAD"),
        "firmware_sha256": hashlib.sha256(firmware.read_bytes()).hexdigest(),
        "source_files": hashes,
    }
    (output / "BUILD.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive = output / "openbuddy-s3-qspi-files.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in sorted(source_files):
            zipped.write(ROOT / name, name)
        zipped.write(micropython / "LICENSE", "licenses/MicroPython-LICENSE.txt")
        zipped.write(idf / "LICENSE", "licenses/ESP-IDF-LICENSE.txt")
        zipped.write(output / "BUILD.json", "BUILD.json")
    (output / "INSTALL.md").write_bytes((ROOT / "README-ESP32-S3-Windows.md").read_bytes())
    names = (firmware.name, archive.name, "BUILD.json", "INSTALL.md")
    (output / "SHA256SUMS.txt").write_text("".join(
        hashlib.sha256((output / name).read_bytes()).hexdigest() + "  " + name + "\n"
        for name in names), encoding="ascii")
    print("Firmware and matching Python files:", output)
    print("Firmware SHA-256:", manifest["firmware_sha256"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--micropython", required=True, type=Path)
    parser.add_argument("--idf", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/s3-qspi")
    args = parser.parse_args()
    package(args.micropython.resolve(), args.idf.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
