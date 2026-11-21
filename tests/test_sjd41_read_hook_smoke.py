import importlib.util
from pathlib import Path
import unittest

BREADBIN_TEST_KIND = "host"  # pure tooling tests; no VICE session

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sjd41" / "read_hook_smoke.py"
SPEC = importlib.util.spec_from_file_location("sjd41_read_hook_smoke", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ReadHookSmokeTests(unittest.TestCase):
    def make_base(self):
        base = bytearray([0xEA] * 0x4000)
        offset = module.HOOK_ADDRESS - 0xC000
        base[offset:offset + 3] = module.HOOK_EXPECT
        return bytes(base)

    def test_builds_transparent_read_hook_image(self):
        base = self.make_base()
        image, extension, manifest = module.build_smoke_image(base)
        self.assertEqual(len(image), 0x8000)
        self.assertEqual(len(extension), 0x4000)
        self.assertEqual(image[:0x4000], extension)
        self.assertEqual(
            extension[module.TRAMPOLINE_ADDRESS - module.EXTENSION_BASE:
                      module.TRAMPOLINE_ADDRESS - module.EXTENSION_BASE + 3],
            bytes.fromhex("4C 0A F5"),
        )
        hook_offset = module.HOOK_ADDRESS - 0xC000
        self.assertEqual(image[0x4000 + hook_offset:0x4000 + hook_offset + 3],
                         bytes.fromhex("20 00 B0"))
        self.assertEqual(image[0x4000 + hook_offset + 3:],
                         base[hook_offset + 3:])
        self.assertEqual(manifest["patches"][0]["address"], "$F4D1")
        self.assertIn("SMOKE TEST ONLY", manifest["warning"])

    def test_rejects_wrong_hook_bytes(self):
        base = bytearray(self.make_base())
        base[module.HOOK_ADDRESS - 0xC000] = 0x00
        with self.assertRaisesRegex(ValueError, "expected JSR"):
            module.build_smoke_image(bytes(base))

    def test_rejects_wrong_base_size(self):
        with self.assertRaisesRegex(ValueError, "16384 bytes"):
            module.build_smoke_image(bytes(10))


if __name__ == "__main__":
    unittest.main()
