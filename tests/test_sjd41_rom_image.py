import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BREADBIN_TEST_KIND = "host"  # pure tooling tests; no VICE session

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sjd41" / "rom_image.py"
SPEC = importlib.util.spec_from_file_location("rom_image", SCRIPT)
rom_image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rom_image)


class RomImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = bytearray([0xEA] * 0x4000)
        self.base[0x3FFA:0x4000] = bytes.fromhex("01 FF A0 EA 67 FE")
        self.base_path = self.root / "jd.bin"
        self.base_path.write_bytes(self.base)
        self.ext_path = self.root / "extension.bin"
        self.ext_path.write_bytes(bytes([0xFF]) * 0x4000)
        self.manifest_path = self.root / "manifest.json"
        self.output_path = self.root / "out.bin"

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, patches=None, digest=None):
        self.manifest_path.write_text(json.dumps({
            "format": "breadbin-drive-rom-v1",
            "base_sha256": digest or hashlib.sha256(self.base).hexdigest(),
            "patches": patches or [],
        }))

    def test_vectors(self):
        self.assertEqual(
            rom_image.vectors(bytes(self.base)),
            {"nmi": 0xFF01, "reset": 0xEAA0, "irq": 0xFE67},
        )

    def test_address_parser_accepts_supported_forms(self):
        self.assertEqual(rom_image.parse_address("$C010"), 0xC010)
        self.assertEqual(rom_image.parse_address("0xC010"), 0xC010)
        self.assertEqual(rom_image.parse_address(0xC010), 0xC010)

    def test_address_parser_rejects_boolean(self):
        with self.assertRaisesRegex(ValueError, "boolean"):
            rom_image.parse_address(True)

    def test_build_places_extension_before_jd_bank(self):
        self.manifest()
        self.assertEqual(
            rom_image.build(self.base_path, self.ext_path,
                            self.manifest_path, self.output_path), 0
        )
        result = self.output_path.read_bytes()
        self.assertEqual(len(result), 0x8000)
        self.assertEqual(result[:0x4000], self.ext_path.read_bytes())
        self.assertEqual(result[0x4000:], self.base_path.read_bytes())

    def test_guarded_patch_changes_only_requested_bytes(self):
        self.manifest([{"address": "$C010", "expect": "EA EA", "replace": "4C 00"}])
        self.assertEqual(
            rom_image.build(self.base_path, self.ext_path,
                            self.manifest_path, self.output_path), 0
        )
        result = self.output_path.read_bytes()
        self.assertEqual(result[0x4010:0x4012], bytes.fromhex("4C 00"))
        self.assertEqual(result[0x4012:0x4020], self.base[0x12:0x20])

    def test_rejects_wrong_base_hash(self):
        self.manifest(digest="0" * 64)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            rom_image.build(self.base_path, self.ext_path,
                            self.manifest_path, self.output_path)

    def test_rejects_stale_patch_bytes(self):
        self.manifest([{"address": "$C010", "expect": "00", "replace": "EA"}])
        with self.assertRaisesRegex(ValueError, "expected 00"):
            rom_image.build(self.base_path, self.ext_path,
                            self.manifest_path, self.output_path)

    def test_rejects_overlapping_patches(self):
        self.manifest([
            {"address": "$C010", "expect": "EA EA", "replace": "EA EA"},
            {"address": "$C011", "expect": "EA", "replace": "EA"},
        ])
        with self.assertRaisesRegex(ValueError, "overlaps"):
            rom_image.build(self.base_path, self.ext_path,
                            self.manifest_path, self.output_path)


if __name__ == "__main__":
    unittest.main()
