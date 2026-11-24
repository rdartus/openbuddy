import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from pc.pet import (BACKGROUND, CLIPS, LEGACY_BACKGROUND, OUTPUT_SIZE, STATE_CLIPS,
                    clip_frames, convert, has_pillow, pack_output, parse_codex_pet_url,
                    rgb565, valid_id, write_pack_from_clips)
from device.pet_format import BACKGROUND as SHARED_BACKGROUND, FRAME_SIZE


class ConversionTests(unittest.TestCase):
    def test_one_pack_format_and_default_path_for_both_boards(self):
        self.assertIs(BACKGROUND, SHARED_BACKGROUND)
        self.assertIs(OUTPUT_SIZE, FRAME_SIZE)
        self.assertEqual(BACKGROUND, (0, 0, 0))
        self.assertEqual(pack_output("test-pet"), Path("build/pets/test-pet-black"))
        self.assertEqual(pack_output("test-pet", LEGACY_BACKGROUND),
                         Path("build/pets/test-pet"))

    def test_rgb565_high_byte_first(self):
        image = Image.new("RGB", (4, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)])
        self.assertEqual(rgb565(image), b"\xf8\x00\x07\xe0\x00\x1f\xff\xff")

    def test_generated_pack_dimensions_sizes_and_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = root / "sheet.png"
            Image.new("RGBA", (1536, 2288), (255, 0, 0, 255)).save(sheet)
            output = root / "pack"
            manifest = convert(sheet, output, "test-pet", {"author": "test"})
            self.assertEqual((manifest["width"], manifest["height"]), (96, 104))
            self.assertEqual(manifest["background"], [0, 0, 0])
            self.assertEqual(manifest["states"], STATE_CLIPS)
            self.assertEqual(sum(value["frames"] for value in manifest["animations"].values()), 73)
            self.assertEqual(manifest["animations"]["look"]["frames"], 16)
            self.assertEqual(manifest["animations"]["retry"]["frames"], 16)
            for name, clip in CLIPS.items():
                animation = manifest["animations"][name]
                data = (output / animation["file"]).read_bytes()
                self.assertEqual(len(data), clip_frames(clip) * 96 * 104 * 2)
                self.assertEqual(data[:2], b"\xf8\x00")
                self.assertEqual(hashlib.sha256(data).hexdigest(), animation["sha256"])
            self.assertEqual(json.loads((output / "manifest.json").read_text())["id"], "test-pet")
            with self.assertRaises(ValueError):
                convert(sheet, output, "test-pet", {})

    def test_retry_plays_running_left_then_running_right(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new("RGBA", (1536, 2288), (0, 0, 0, 0))
            sheet.paste((255, 0, 0, 255), (0, 2 * 208, 1536, 3 * 208))  # row 2: running-left
            sheet.paste((0, 0, 255, 255), (0, 1 * 208, 1536, 2 * 208))  # row 1: running-right
            image = root / "sheet.png"
            sheet.save(image)
            output = root / "pack"
            convert(image, output, "test-pet", {})
            data = (output / "retry.rgb565").read_bytes()
            frame = 96 * 104 * 2
            self.assertEqual(data[:2], b"\xf8\x00")
            self.assertEqual(data[8 * frame:8 * frame + 2], b"\x00\x1f")

    def test_black_amoled_pack_composites_translucent_edges_on_black(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = Image.new("RGBA", (1536, 2288), (0, 0, 0, 0))
            sheet.paste((0, 0, 255, 128), (0, 0, 2, 2))
            image = root / "sheet.png"
            sheet.save(image)
            black = convert(image, root / "black", "test-pet", {})
            dark = convert(image, root / "dark", "test-pet", {}, background=(8, 12, 20))
            self.assertEqual(black["background"], [0, 0, 0])
            self.assertEqual(dark["background"], [8, 12, 20])
            black_frame = (root / "black" / "idle.rgb565").read_bytes()
            dark_frame = (root / "dark" / "idle.rgb565").read_bytes()
            self.assertEqual(black_frame[:2], b"\x00\x10")  # Half-alpha blue on black.
            self.assertEqual(black_frame[2:4], b"\x00\x00")  # Transparent edge is truly off.
            self.assertEqual(dark_frame[2:4], b"\x08\x62")
            self.assertNotEqual(black_frame[:2], dark_frame[:2])

    def test_unsupported_background_is_rejected_without_writing_a_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pack"
            with self.assertRaisesRegex(ValueError, "background"):
                convert("unused.png", output, "test-pet", {}, background=(1, 2, 3))
            self.assertFalse(output.exists())

    def test_v1_atlas_has_no_look_clip_and_thinking_falls_back_to_idle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sheet = root / "sheet.png"
            Image.new("RGBA", (1536, 1872), (255, 0, 0, 255)).save(sheet)
            manifest = convert(sheet, root / "pack", "test-pet", {})
            self.assertNotIn("look", manifest["animations"])
            self.assertEqual(manifest["states"]["thinking"], "idle")
            for clip in manifest["states"].values():
                self.assertIn(clip, manifest["animations"])

    def test_invalid_ids_cannot_escape_pack_directory(self):
        for value in ("../escape", "a/b", "", "UPPER", "a\\b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid_id(value)

    def test_parse_codex_pet_url_accepts_hash_path_and_slug(self):
        self.assertEqual(parse_codex_pet_url("https://codex-pets.net/#/pets/ferris-rust-crab"), "ferris-rust-crab")
        self.assertEqual(parse_codex_pet_url("https://codex-pets.net/#/pets/monthly-salary-cat"), "monthly-salary-cat")
        self.assertEqual(parse_codex_pet_url("https://codex-pets.net/pets/ferris-rust-crab/?v=1"), "ferris-rust-crab")
        self.assertEqual(parse_codex_pet_url("  ferris-rust-crab  "), "ferris-rust-crab")
        for bad in (
            "",
            "http://codex-pets.net/#/pets/ferris-rust-crab",
            "https://evil.example/#/pets/ferris-rust-crab",
            "https://codex-pets.net/#/other/page",
            "https://codex-pets.net/#/pets/../escape",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_codex_pet_url(bad)

    def test_write_pack_from_clips_without_pillow_and_custom_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ferris-rust-crab"
            frame_bytes = OUTPUT_SIZE[0] * OUTPUT_SIZE[1] * 2
            clip_payloads = {
                "idle": (b"\x00\x00" * (OUTPUT_SIZE[0] * OUTPUT_SIZE[1] * 2), 2),
                "waving": (b"\xf8\x00" * (OUTPUT_SIZE[0] * OUTPUT_SIZE[1] * 4), 4),
            }
            manifest = write_pack_from_clips(
                output,
                "ferris-rust-crab",
                {"name": "Ferris", "author": "mahirmehtizadee"},
                clip_payloads,
                states={"thinking": "waving", "working": "waving"},
            )
            self.assertEqual(manifest["id"], "ferris-rust-crab")
            self.assertEqual(manifest["states"]["thinking"], "waving")
            self.assertEqual(manifest["states"]["working"], "waving")
            self.assertEqual(manifest["states"]["error"], "idle")
            self.assertEqual((output / "waving.rgb565").stat().st_size, 4 * frame_bytes)
            self.assertTrue((output / "manifest.json").is_file())

    def test_has_pillow_returns_false_when_pil_is_missing(self):
        with patch("importlib.util.find_spec", side_effect=ModuleNotFoundError("No module named 'PIL'")):
            self.assertFalse(has_pillow())
        with patch("importlib.util.find_spec", return_value=None):
            self.assertFalse(has_pillow())


if __name__ == "__main__":
    unittest.main()
