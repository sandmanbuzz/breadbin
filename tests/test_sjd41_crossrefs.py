import importlib.util
import sys
from pathlib import Path
import unittest

BREADBIN_TEST_KIND = "host"  # pure tooling tests; no VICE session

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sjd41" / "crossrefs.py"
SPEC = importlib.util.spec_from_file_location("sjd41_crossrefs", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class CrossReferenceTests(unittest.TestCase):
    def test_finds_only_changed_extension_calls(self):
        base = bytearray([0xEA] * 0x4000)
        sjd = bytearray([0xEA] * 0x8000)
        # The upper SJD bank starts at file offset $4000 and maps at CPU $C000.
        sjd[0x4000:0x4003] = bytes.fromhex("20 34 B2")
        sjd[0x4010:0x4013] = bytes.fromhex("4C 00 80")
        # This unchanged byte pattern is not reported.
        base[0x20:0x23] = bytes.fromhex("20 00 90")
        sjd[0x4020:0x4023] = bytes.fromhex("20 00 90")

        refs = module.find_cross_references(bytes(base), bytes(sjd))
        self.assertEqual(
            [(r.source, r.mnemonic, r.target) for r in refs],
            [(0xC000, "JSR", 0xB234), (0xC010, "JMP", 0x8000)],
        )

    def test_rejects_wrong_image_sizes(self):
        with self.assertRaisesRegex(ValueError, "JD base"):
            module.find_cross_references(bytes(10), bytes(0x8000))
        with self.assertRaisesRegex(ValueError, "SJD image"):
            module.find_cross_references(bytes(0x4000), bytes(10))


if __name__ == "__main__":
    unittest.main()
