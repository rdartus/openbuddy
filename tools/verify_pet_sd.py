"""Verify all copied bytes before activating the pack; run after prepare_pet_sd."""

import binascii
import hashlib
import json
import os

if os.stat(pack_root + "/manifest.json")[6] > 8192:
    raise ValueError("Manifest too large")
with open(pack_root + "/manifest.json", "rb") as handle:
    manifest_data = handle.read()
if binascii.hexlify(hashlib.sha256(manifest_data).digest()).decode() != MANIFEST_SHA256:
    raise ValueError("Transferred manifest checksum mismatch")
manifest = json.loads(manifest_data.decode())
if (manifest.get("id") != PACK_ID or manifest.get("format") != "RGB565-BE"
        or manifest.get("version") != 1):
    raise ValueError("Unexpected transferred pack")
buffer = bytearray(8192)
for animation in manifest["animations"].values():
    name = animation["file"]
    if ("/" in name or "\\" in name or ".." in name
            or not name.endswith(".rgb565")):
        raise ValueError("Unsafe transferred filename")
    path = pack_root + "/" + name
    if os.stat(path)[6] != animation["bytes"]:
        raise ValueError("Transferred size mismatch")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            count = handle.readinto(buffer)
            if not count:
                break
            digest.update(memoryview(buffer)[:count])
    if binascii.hexlify(digest.digest()).decode() != animation["sha256"]:
        raise ValueError("Transferred checksum mismatch: " + name)
    print("Verified:", name)
with open(ASSET_ROOT + "/active.json.tmp", "w") as handle:
    json.dump({"pet": PACK_ID}, handle)
    handle.flush()
os.sync()
os.rename(ASSET_ROOT + "/active.json.tmp", ASSET_ROOT + "/active.json")
os.sync()
os.chdir("/")
if getattr(cfg, "BOARD_MODEL", "") == "waveshare-s3-amoled-164-v2":
    # Switch the reader only after all assets and the active selection are verified.
    with open("/openbuddy-storage.txt.tmp", "w") as handle:
        handle.write(SELECTED_STORAGE)
        handle.flush()
    os.sync()
    os.rename("/openbuddy-storage.txt.tmp", "/openbuddy-storage.txt")
    os.sync()
if SELECTED_STORAGE == "sd":
    vfs.umount(cfg.SD_MOUNT)
    sd.deinit()
print("Pet activated:", PACK_ID, "storage:", SELECTED_STORAGE, "root:", ASSET_ROOT)
