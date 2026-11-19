"""Package native firmware with the exact allowlisted Python deployment and hashes."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BOARD = "OPENBUDDY_S3_AMOLED_V2"
BOARD_FILES = {"firmware/boards/" + BOARD + "/" + name for name in (
    "mpconfigboard.cmake", "mpconfigboard.h", "sdkconfig.board", "manifest.py", "openbuddy_build.py")}
sys.path.insert(0, str(ROOT))
from pc.deploy import FILES
from pc.pet import CLIPS, OUTPUT_SIZE, clip_frames


def flash_budget(build):
    """Check actual images/partitions, then budget Python and two standard v2 packs."""
    flash = 16 * 1024 * 1024
    partitions = []
    data = (build / "partition_table/partition-table.bin").read_bytes()
    for offset in range(0, len(data) - 31, 32):
        magic, kind, subtype, start, size, name, flags = struct.unpack_from("<HBBII16sI", data, offset)
        if magic != 0x50AA:  # MD5 record or erased tail.
            break
        partitions.append((kind, subtype, start, size, name.rstrip(b"\0")))
    # MicroPython v1.29 creates its VFS dynamically after the final partition.
    # Fail closed if this build ever changes the documented standard layout.
    if partitions != [(1, 2, 0x9000, 0x6000, b"nvs"),
                      (1, 1, 0xF000, 0x1000, b"phy_init"),
                      (0, 0, 0x10000, 0x1F0000, b"factory")]:
        raise ValueError("Unexpected partition layout; recheck the internal flash budget")
    vfs_offset = max(start + size for _, _, start, size, _ in partitions)
    app_bytes = (build / "micropython.bin").stat().st_size
    if not 0 < app_bytes <= partitions[-1][3]:
        raise ValueError("MicroPython application exceeds its flash partition")
    if not 0 < (build / "firmware.bin").stat().st_size <= vfs_offset:
        raise ValueError("Combined firmware overlaps the persistent VFS")
    block = 4096

    def allocated(sizes):
        return sum((size + block - 1) // block * block for size in sizes) + block * (len(sizes) + 8)

    python_sizes = [(ROOT / "device" / name).stat().st_size for name in FILES]
    frame_bytes = OUTPUT_SIZE[0] * OUTPUT_SIZE[1] * 2
    pixel_sizes = [clip_frames(clip) * frame_bytes for clip in CLIPS.values()]
    python_budget = allocated(python_sizes)
    # Maximum manifest, active selection and interrupted-install marker, not preview/source art.
    pet_budget = allocated(pixel_sizes + [8192, 256, 256])
    reserve = 256 * 1024
    required = python_budget + 2 * pet_budget + reserve
    vfs_bytes = flash - vfs_offset
    if required > vfs_bytes:
        raise ValueError("Python files and standard pet packs do not fit internal flash with reserve")
    return {"app_bytes": app_bytes, "app_partition_bytes": partitions[-1][3],
            "vfs_offset": vfs_offset, "vfs_bytes": vfs_bytes,
            "python_bytes": sum(python_sizes), "python_budget_bytes": python_budget,
            "pet_pixel_bytes": sum(pixel_sizes), "pet_budget_bytes": pet_budget,
            "pack_copies": 2, "reserve_bytes": reserve,
            "required_vfs_bytes": required, "spare_vfs_bytes": vfs_bytes - required}


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
    link_map = (build / "micropython.map").read_text()
    if "amoled_qspi.c.obj" not in link_map:
        raise ValueError("The firmware must link the native amoled_qspi module")
    # Check the compiled transport, not just the current board header: an older
    # binary may still switch the shared PHY to TinyUSB and lose the ROM COM port.
    if not all(re.search(r"\b" + symbol + r"\b", link_map) for symbol in (
            "usb_serial_jtag_init", "usb_serial_jtag_poll_rx", "usb_serial_jtag_tx_strn")):
        raise ValueError("The firmware must link MicroPython USB Serial/JTAG stdio")
    if any(re.search(r"\b" + symbol + r"\b", link_map) for symbol in (
            "mp_usbd_cdc_tx_strn", "usb_phy_init")):
        raise ValueError("The firmware must not switch USB Serial/JTAG to TinyUSB/OTG")
    if "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED=y" not in sdkconfig:
        raise ValueError("The firmware must expose ESP-IDF boot diagnostics over USB Serial/JTAG")
    budget = flash_budget(build)
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "openbuddy-s3-amoled-qspi.bin"
    firmware.write_bytes((build / "firmware.bin").read_bytes())
    source_files = {"device/" + name for name in FILES}
    source_files.update({"pc/__init__.py", "pc/deploy.py", "pc/pet.py", "pc/buddy.py",
                         "pc/requirements.txt", "pc/requirements-assets.txt",
                         "tools/test_amoled.py", "tools/prepare_pet_sd.py", "tools/verify_pet_sd.py",
                         "README-ESP32-S3-Windows.md", "docs/s3-qspi-build.md",
                         "docs/windows-uv-apres-flash.md", "THIRD_PARTY.md"})
    source_files.update({"firmware/amoled_qspi/amoled_qspi.c",
                         "firmware/amoled_qspi/micropython.cmake"})
    source_files.update(BOARD_FILES)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in sorted(source_files)}
    manifest = {
        "board": "waveshare-s3-amoled-164-v2", "experimental": True,
        "micropython_board": BOARD, "flash_bytes": 16 * 1024 * 1024,
        "pet_storage": "internal", "pet_storage_options": ["internal", "sd"],
        "lcd_cs": 46, "qspi_api_version": 4,
        "orientation_sensor": "qmi8658", "flash_budget": budget,
        "usb_backend": "usb-serial-jtag", "usb_vid": 0x303A, "usb_pid": 0x1001,
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
    print("Internal flash budget:", json.dumps(budget, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--micropython", required=True, type=Path)
    parser.add_argument("--idf", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/s3-qspi")
    args = parser.parse_args()
    package(args.micropython.resolve(), args.idf.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
