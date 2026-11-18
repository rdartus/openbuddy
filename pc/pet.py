"""Convert Codex Pets atlases and install local RGB565 packs over USB."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from device.pet_format import BACKGROUND, FRAME_SIZE as OUTPUT_SIZE

DEFAULT_PET = "super-saiyan-goku-combat"
LEGACY_BACKGROUND = (8, 12, 20)
CELL = (192, 208)
INSTALL_TIMEOUT = 600
RESET_TIMEOUT = 20
# Codex Pets src/domain/config.ts, blob 12403682002a5f4415c65e1514317c7e978161bc.
# A clip is a sequence of (atlas row, frame count) segments played back to back.
# Rows 9-10 only exist in v2 atlases: sixteen head-turn frames of the idle pose.
CLIPS = {"idle": ((0, 6),), "waving": ((3, 4),), "jumping": ((4, 5),),
         "failed": ((5, 8),), "waiting": ((6, 6),), "running": ((7, 6),),
         "review": ((8, 6),),
         "look": ((9, 8), (10, 8)),
         "retry": ((2, 8), (1, 8))}  # running-left, then running-right
STATE_CLIPS = {"offline": "idle", "idle": "idle", "thinking": "look",
               "working": "running", "permission": "review", "question": "waving",
               "success": "jumping", "error": "failed", "retry": "retry", "pairing": "waiting"}


def clip_frames(clip):
    return sum(count for _, count in clip)


def layout(sheet_height):
    """v1 atlases have no look rows: thinking falls back to the idle clip."""
    if sheet_height >= 11 * CELL[1]:
        return CLIPS, STATE_CLIPS
    clips = {name: clip for name, clip in CLIPS.items() if name != "look"}
    return clips, dict(STATE_CLIPS, thinking="idle")


def valid_id(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value):
        raise ValueError("Invalid pet id")
    return value


def pack_output(pet_id, background=BACKGROUND):
    """Use one black pack for every board, without overwriting legacy dark packs."""
    valid_id(pet_id)
    if background not in (BACKGROUND, LEGACY_BACKGROUND):
        raise ValueError("Unsupported pet background")
    return Path("build/pets") / (pet_id + ("-black" if background == BACKGROUND else ""))


def download(url, destination, limit):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "codex-pets.net":
        raise ValueError("Only HTTPS assets from codex-pets.net are accepted")
    request = Request(url, headers={"User-Agent": "OpenBuddy/0.1 (local asset conversion)"})
    with urlopen(request, timeout=30) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "codex-pets.net":
            raise ValueError("Unexpected asset redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds size limit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def rgb565(image):
    """Big-endian RGB565; alpha must already be composited on the background."""
    pixels = image.convert("RGB").tobytes()
    result = bytearray(len(pixels) // 3 * 2)
    target = 0
    for offset in range(0, len(pixels), 3):
        red, green, blue = pixels[offset:offset + 3]
        color = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        result[target] = color >> 8
        result[target + 1] = color & 255
        target += 2
    return result


def convert(sheet_path, output, pet_id, source, frame_ms=None, force=False,
            background=BACKGROUND):
    from PIL import Image, ImageDraw

    valid_id(pet_id)
    if background not in (BACKGROUND, LEGACY_BACKGROUND):
        raise ValueError("Unsupported pet background")
    if frame_ms is not None and not 100 <= frame_ms <= 2000:
        raise ValueError("Frame duration must be between 100 and 2000 ms")
    if output.exists() and any(output.iterdir()) and not force:
        raise ValueError("Output is not empty; use --force to replace generated pack files")
    with Image.open(sheet_path) as image:
        if image.size not in ((1536, 1872), (1536, 2288)):
            raise ValueError("Expected a Codex Pets v1/v2 atlas (1536x1872 or 1536x2288)")
        sheet = image.convert("RGBA")
    output.mkdir(parents=True, exist_ok=True)
    clips, states = layout(sheet.height)
    manifest = {
        "version": 1, "id": pet_id, "format": "RGB565-BE",
        "width": OUTPUT_SIZE[0], "height": OUTPUT_SIZE[1],
        "background": list(background), "states": dict(states),
        "source": source, "animations": {},
    }
    preview = Image.new("RGB", (len(clips) * 112, 128), background)
    draw = ImageDraw.Draw(preview)
    for index, (name, clip) in enumerate(clips.items()):
        path = output / (name + ".rgb565")
        digest = hashlib.sha256()
        count = clip_frames(clip)
        with path.open("wb") as handle:
            frame_number = 0
            for row, segment in clip:
                for frame in range(segment):
                    box = (frame * CELL[0], row * CELL[1], (frame + 1) * CELL[0], (row + 1) * CELL[1])
                    cell = sheet.crop(box).resize(OUTPUT_SIZE, Image.Resampling.NEAREST)
                    opaque = Image.new("RGBA", OUTPUT_SIZE, background + (255,))
                    opaque.alpha_composite(cell)
                    data = rgb565(opaque)
                    handle.write(data)
                    digest.update(data)
                    if frame_number == 0:
                        preview.paste(opaque.convert("RGB"), (index * 112 + 8, 0))
                    frame_number += 1
        draw.text((index * 112 + 8, 110), name, fill=(225, 233, 245))
        manifest["animations"][name] = {
            "file": path.name, "frames": count,
            "frame_ms": frame_ms or max(count * 260, 1400) // count,
            "sha256": digest.hexdigest(), "bytes": path.stat().st_size,
        }
    preview.save(output / "preview.png")
    # Publish the manifest last: a failed conversion is not a complete pack.
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def convert_command(args):
    pet_id = valid_id(args.pet)
    cache = Path(".cache/pets") / pet_id
    metadata = cache / "catalog.json"
    download("https://codex-pets.net/api/pets/" + pet_id, metadata, 128 * 1024)
    pet = json.loads(metadata.read_text(encoding="utf-8"))["pet"]
    sheet = cache / "spritesheet.webp"
    download(pet["spritesheetUrl"], sheet, 16 * 1024 * 1024)
    source = {
        "url": "https://codex-pets.net/#/pets/" + pet_id,
        "spritesheet_url": pet["spritesheetUrl"],
        "author": pet.get("ownerHandle") or pet.get("ownerName") or "unknown",
        "sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
        "rights": "Community artwork; redistribution rights not verified; local use only",
    }
    background = BACKGROUND if args.background == "black" else LEGACY_BACKGROUND
    output = Path(args.output) if args.output else pack_output(pet_id, background)
    manifest = convert(sheet, output, pet_id, source, args.frame_ms, args.force, background)
    total = sum(item["bytes"] for item in manifest["animations"].values())
    print("Pack:", output)
    print("%d animations, %d frames, %d bytes; RGB565-BE 96x104" % (
        len(manifest["animations"]), sum(item["frames"] for item in manifest["animations"].values()), total))
    print("Preview:", output / "preview.png")


def install(args):
    timeout = getattr(args, "timeout", INSTALL_TIMEOUT)
    if timeout <= 0:
        raise ValueError("--timeout must be positive")
    folder = Path(args.pack).resolve()
    manifest_path = folder / "manifest.json"
    if manifest_path.stat().st_size > 8192:
        raise ValueError("Manifest too large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pet_id = valid_id(manifest["id"])
    if manifest.get("version") != 1 or manifest.get("format") != "RGB565-BE":
        raise ValueError("Unsupported pack")
    filenames = []
    sizes = []
    if not isinstance(manifest["animations"], dict) or not 1 <= len(manifest["animations"]) <= 16:
        raise ValueError("Invalid animation table")
    for animation in manifest["animations"].values():
        name = animation["file"]
        if not re.fullmatch(r"[a-z0-9-]+\.rgb565", name):
            raise ValueError("Unsafe pack filename")
        path = folder / name
        if type(animation["bytes"]) is not int or not 0 < animation["bytes"] <= 104 * 104 * 2 * 64:
            raise ValueError("Invalid animation size: " + name)
        if path.stat().st_size != animation["bytes"]:
            raise ValueError("Size mismatch: " + name)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(8192):
                digest.update(chunk)
        if digest.hexdigest() != animation["sha256"]:
            raise ValueError("Checksum mismatch: " + name)
        if name not in filenames:
            filenames.append(name)
            sizes.append(animation["bytes"])
    sizes.append(manifest_path.stat().st_size)
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-u", "-m", "mpremote", "connect", args.port,
               "exec", "PACK_ID=%r; REPLACE=%r; STORAGE=%r; PACK_SIZES=%r; MANIFEST_SHA256=%r" % (
                   pet_id, args.replace, args.storage, sizes,
                   hashlib.sha256(manifest_path.read_bytes()).hexdigest()),
               "+", "run", str(root / "tools/prepare_pet_sd.py")]
    for name in filenames + ["manifest.json"]:
        command.extend(["+", "fs", "cp", str(folder / name), ":" + name])
    command.extend(["+", "run", str(root / "tools/verify_pet_sd.py")])
    print("Installing pack (%s, %d bytes); BLE will disconnect during USB transfer." % (
        args.storage, sum(sizes)), flush=True)
    try:
        # Kill and reap a stalled mpremote before opening the same port for reset.
        subprocess.run(command, timeout=timeout, check=True)
    finally:
        reset_ok = False
        try:
            subprocess.run([sys.executable, "-m", "mpremote", "connect", args.port, "reset"],
                           timeout=RESET_TIMEOUT, check=True)
            reset_ok = True
        except (OSError, subprocess.SubprocessError) as error:
            # Preserve a transfer failure, including timeouts and Ctrl+C.
            print("Warning: automatic reset failed (%s); press RST on the board." %
                  type(error).__name__, file=sys.stderr)
    if not reset_ok:
        raise OSError("Pack installed, but the board could not be restarted")


def main():
    parser = argparse.ArgumentParser(description="Convert and install OpenBuddy pet animations")
    commands = parser.add_subparsers(dest="command", required=True)
    conversion = commands.add_parser("convert", help="Download and convert a Codex Pets atlas")
    conversion.add_argument("--pet", default=DEFAULT_PET)
    conversion.add_argument("--output")
    conversion.add_argument("--frame-ms", type=int)
    conversion.add_argument("--force", action="store_true")
    conversion.add_argument("--background", choices=("black", "dark"), default="black",
                            help="Black for both boards (default); dark for older firmware only")
    installation = commands.add_parser("install", help="Copy and verify a pack on ESP32 storage via USB")
    installation.add_argument("pack")
    installation.add_argument("--port", default="auto")
    installation.add_argument("--storage", choices=("auto", "sd", "internal"), default="auto",
                              help="Follow the board policy by default; S3 AMOLED v2 requires internal flash")
    installation.add_argument("--replace", action="store_true", help="Replace an existing OpenBuddy pack")
    installation.add_argument("--timeout", type=int, default=INSTALL_TIMEOUT, metavar="SECONDS",
                              help="Maximum install duration (default: %(default)s seconds)")
    args = parser.parse_args()
    try:
        if args.command == "convert":
            convert_command(args)
        else:
            install(args)
    except subprocess.TimeoutExpired as error:
        parser.exit(1, "Installation timed out after %s seconds; mpremote was stopped. "
                    "The pack may be incomplete; retry with --replace.\n" % error.timeout)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, "Error: %s\n" % error)


if __name__ == "__main__":
    main()
