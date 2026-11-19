"""Run in RAM, in one mpremote command chain; never format any device."""

import json
import os
import board_config as cfg


def valid_name(value):
    return (isinstance(value, str) and 1 <= len(value) <= 64
            and value[0] in "abcdefghijklmnopqrstuvwxyz0123456789"
            and all(character in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in value))


if not valid_name(PACK_ID):
    raise ValueError("Unsafe pack id")
STORAGE = globals().get("STORAGE", "auto")
if STORAGE not in ("auto", "sd", "internal"):
    raise ValueError("Unknown storage selection")
if (not isinstance(PACK_SIZES, (list, tuple)) or not 2 <= len(PACK_SIZES) <= 17
        or any(type(size) is not int or not 0 < size <= 104 * 104 * 2 * 64 for size in PACK_SIZES)
        or PACK_SIZES[-1] > 8192):
    raise ValueError("Invalid pack sizes")


def capacity(path):
    stats = os.statvfs(path)
    block = stats[1] or stats[0]
    free = block * stats[4]  # f_bavail, not f_bfree or the partition size.
    # Budget a full extra pack even on replacement, plus allocation/metadata overhead.
    required = (sum((size + block - 1) // block * block for size in PACK_SIZES)
                + block * (len(PACK_SIZES) + 8) + 256 * 1024)
    print("Storage capacity:", path, "free", free, "required", required, "bytes (reserve 262144)")
    return free >= required


SELECTED_STORAGE = STORAGE
if STORAGE == "auto" and getattr(cfg, "PET_STORAGE", "auto") in ("internal", "sd"):
    SELECTED_STORAGE = cfg.PET_STORAGE
elif STORAGE == "auto":
    model = str(getattr(cfg, "BOARD_MODEL", "")).upper()
    prefer_internal = (bool(model) and "C6" not in model
                       and getattr(cfg, "DISPLAY_DRIVER", "") == "co5300")
    SELECTED_STORAGE = "internal" if prefer_internal and capacity("/") else "sd"
    if prefer_internal and SELECTED_STORAGE == "sd":
        print("Insufficient internal flash; falling back to SD")
if (getattr(cfg, "BOARD_MODEL", "") == "waveshare-s3-amoled-164-v2"
        and SELECTED_STORAGE == "sd"):
    # The TF holds the pack, but the verified choice still needs a tiny
    # atomic marker on the internal VFS. Fail before transferring any assets.
    flash = os.statvfs("/")
    if (flash[1] or flash[0]) * flash[4] < 32 * 1024:
        raise ValueError("Insufficient internal flash for the TF storage preference (32 KiB required)")
if SELECTED_STORAGE == "internal":
    if not capacity("/"):
        raise ValueError("Insufficient internal flash space (including 256 KiB reserve)")
    ASSET_ROOT = "/openbuddy"
else:
    try:
        import vfs
        from machine import Pin, SDCard, SPI

        if getattr(cfg, "DISPLAY_DRIVER", "") != "co5300":
            Pin(cfg.LCD_CS, Pin.OUT, value=1)
        Pin(cfg.SD_CS, Pin.OUT, value=1)
        spi_id = getattr(cfg, "SD_SPI_ID", cfg.LCD_SPI_ID)
        sclk = getattr(cfg, "SD_SCLK", cfg.LCD_SCLK)
        mosi = getattr(cfg, "SD_MOSI", cfg.LCD_MOSI)
        spi = SPI(spi_id, baudrate=1_000_000, sck=Pin(sclk),
                  mosi=Pin(mosi), miso=Pin(cfg.SD_MISO))
        spi.deinit()
        # Native SD slot 2 maps to SPI3 on S3, unlike machine.SPI numbering.
        sd = SDCard(slot=2, sck=Pin(sclk), mosi=Pin(mosi),
                    miso=Pin(cfg.SD_MISO), cs=Pin(cfg.SD_CS), freq=10_000_000)
        vfs.mount(sd, cfg.SD_MOUNT)
    except (ImportError, AttributeError, OSError, ValueError) as error:
        raise ValueError("SD unavailable for storage=%s: %s" % (STORAGE, error))
    if not capacity(cfg.SD_MOUNT):
        raise ValueError("Insufficient SD space (including 256 KiB reserve)")
    ASSET_ROOT = cfg.SD_MOUNT.rstrip("/") + "/openbuddy"
print("Selected storage:", SELECTED_STORAGE, "asset root:", ASSET_ROOT)
for path in (ASSET_ROOT, ASSET_ROOT + "/pets"):
    try:
        os.mkdir(path)
    except OSError as error:
        if error.args[0] != 17:
            raise
pack_root = ASSET_ROOT + "/pets/" + PACK_ID
try:
    os.stat(pack_root)
except OSError as error:
    if error.args[0] != 2:
        raise
    os.mkdir(pack_root)
else:
    if not REPLACE:
        raise ValueError("Pack already exists; explicitly allow replacement")
    try:
        if os.stat(pack_root + "/manifest.json")[6] > 8192:
            raise ValueError("Existing manifest too large")
        with open(pack_root + "/manifest.json") as handle:
            existing = json.load(handle)
    except OSError as error:
        if error.args[0] != 2:
            raise
        if os.stat(pack_root + "/openbuddy-install.json")[6] > 256:
            raise ValueError("Existing install marker too large")
        with open(pack_root + "/openbuddy-install.json") as handle:
            existing = json.load(handle)
    if existing.get("id") != PACK_ID or existing.get("format") != "RGB565-BE":
        raise ValueError("Existing directory is not this OpenBuddy pack")
with open(pack_root + "/openbuddy-install.json", "w") as handle:
    json.dump({"id": PACK_ID, "format": "RGB565-BE", "version": 1}, handle)
    handle.flush()
os.sync()
os.chdir(pack_root)
print("Storage target ready:", pack_root)
