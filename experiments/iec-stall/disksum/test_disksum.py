"""Host-only tests for disksum.py: the checksum definition, the d64 layout and the comparer. No hardware.

    python3 -m unittest experiments/iec-stall/disksum/test_disksum.py
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import disksum  # noqa: E402


class Checksum(unittest.TestCase):
    def test_vectors(self):
        self.assertEqual(disksum.checksum(bytes(256)), (0, 0, 0))
        self.assertEqual(disksum.checksum(b"\xff" * 256), (0x00, 0xFF, 0x00))      # 256 * 255 = 0xFF00
        self.assertEqual(disksum.checksum(bytes(range(256))), (0x80, 0x7F, 0x00))  # 32640 = 0x7F80; XOR of 0..255 is 0

    def test_a_single_changed_byte_always_changes_the_sum(self):
        base = bytes(random.Random(7).randrange(256) for _ in range(256))
        for i in range(256):
            changed = bytearray(base)
            changed[i] ^= 0x01
            self.assertNotEqual(disksum.checksum(bytes(changed))[:2], disksum.checksum(base)[:2], i)


class CommandString(unittest.TestCase):
    """The exact text the reader sends. Mirrors disksum.s; the 6502 path itself is only checked on hardware."""

    def test_sectors_0_9_10_and_682(self):
        lay = disksum.layout()
        self.assertEqual(disksum.command_string(*lay[0]), "U1:2 0 1 0")       # sector 0
        self.assertEqual(disksum.command_string(*lay[9]), "U1:2 0 1 9")       # sector 9
        self.assertEqual(disksum.command_string(*lay[10]), "U1:2 0 1 10")     # sector 10
        self.assertEqual(disksum.command_string(*lay[682]), "U1:2 0 35 16")   # the last sector, index 682

    def test_no_padded_form_is_ever_produced(self):
        for t, s in disksum.layout():
            text = disksum.command_string(t, s)
            for field in text.split()[2:]:
                self.assertFalse(len(field) > 1 and field.startswith("0"), text)


class Layout(unittest.TestCase):
    def test_683_sectors_in_d64_order(self):
        lay = disksum.layout()
        self.assertEqual(len(lay), 683)
        self.assertEqual(lay[0], (1, 0))
        self.assertEqual(lay[20], (1, 20))
        self.assertEqual(lay[21], (2, 0))
        self.assertEqual(lay[-1], (35, 16))

    def test_track_counts_match_the_d64_format(self):
        self.assertEqual([disksum.spt(t) for t in (1, 17, 18, 24, 25, 30, 31, 35)], [21, 21, 19, 19, 18, 18, 17, 17])


class Comparer(unittest.TestCase):
    def setUp(self):
        self.image = bytes(random.Random(1).randrange(256) for _ in range(683 * 256))
        self.want = disksum.expected(self.image)

    def test_identical_disks_match_everywhere(self):
        matches, diffs, first = disksum.compare(list(self.want), self.want)
        self.assertEqual((matches, diffs, first), (683, [], None))

    def test_a_changed_sector_is_named(self):
        k = 400                                  # somewhere in the middle
        bad = bytearray(self.image)
        bad[k * 256 + 17] ^= 0x40
        got = disksum.expected(bytes(bad))
        matches, diffs, first = disksum.compare(got, self.want)
        self.assertEqual(diffs, [k])
        self.assertEqual(matches, 682)
        self.assertEqual(first, disksum.layout()[k])

    def test_the_first_difference_is_reported_first(self):
        bad = bytearray(self.image)
        for k in (600, 3):
            bad[k * 256] ^= 0x01
        matches, diffs, first = disksum.compare(disksum.expected(bytes(bad)), self.want)
        self.assertEqual(diffs, [3, 600])
        self.assertEqual(first, disksum.layout()[3])

    def test_a_short_read_back_is_visible(self):
        got = list(self.want)
        got[10] = (0, 0, 0)
        matches, diffs, first = disksum.compare(got, self.want)
        self.assertEqual(diffs, [10])


if __name__ == "__main__":
    unittest.main()
