import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sjd41" / "generator_records.py"
SPEC = importlib.util.spec_from_file_location("generator_records", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class PatchTableTests(unittest.TestCase):
    def make_prg(self, records):
        # BASIC at $0801: one line, then the final 00 00 link pointer.
        # The line terminator plus that pointer form the three-zero marker.
        return bytes.fromhex("01 08 07 08 0A 00 99 00 00 00") + records

    def test_finds_appended_patch_table(self):
        prg = self.make_prg(bytes.fromhex("00 60 02 AA BB 00 00 00"))
        table = module.parse_table(prg)
        self.assertEqual((table.marker, table.start), (0x0806, 0x0809))
        self.assertEqual(len(table.records), 1)
        self.assertEqual(table.records[0].address, 0x6000)
        self.assertEqual(table.records[0].payload, bytes.fromhex("AA BB"))

    def test_zero_length_byte_means_256(self):
        payload = bytes(range(256))
        table = module.parse_table(self.make_prg(bytes.fromhex("34 12 00") + payload + bytes(3)))
        self.assertEqual(table.records[0].address, 0x1234)
        self.assertEqual(table.records[0].payload, payload)

    def test_record_can_cross_8k_bank_boundary(self):
        table = module.parse_table(self.make_prg(bytes.fromhex("FF 7F 03 11 22 33 00 00 00")))
        memory = bytearray(0x10000)
        module.apply(memory, table)
        self.assertEqual(memory[0x7FFF:0x8002], bytes.fromhex("11 22 33"))

    def test_rejects_wrong_load_address(self):
        with self.assertRaisesRegex(ValueError, "load address"):
            module.parse_table(bytes.fromhex("00 20 07 08 0A 00 99 00 00 00 00 00"))


class D64Tests(unittest.TestCase):
    def test_sector_chain_final_sector_count(self):
        raw = bytearray(174848)
        disk = module.D64(bytes(raw))
        first = bytearray(256)
        first[:2] = bytes((1, 1))
        first[2:] = b"A" * 254
        last = bytearray(256)
        last[:2] = bytes((0, 5))  # four payload bytes
        last[2:6] = b"BBBB"
        offset = disk.starts[0] * 256
        raw[offset:offset + 256] = first
        raw[offset + 256:offset + 512] = last
        result = module.D64(bytes(raw)).file(1, 0)
        self.assertEqual(len(result), 258)
        self.assertEqual(result[:254], b"A" * 254)
        self.assertEqual(result[-4:], b"BBBB")


if __name__ == "__main__":
    unittest.main()
