"""Host test: the key decode tables follow the standard C64 layout (no ROM needed)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEAD = {15, 52, 58, 61, 63}


def tables():
    with open(os.path.join(ROOT, "src", "kernel", "keytab.inc")) as f:
        vals = [int(x, 16) for x in re.findall(r"\$([0-9a-f]{2})", re.sub(r";.*", "", f.read()))]
    return [vals[i * 64:(i + 1) * 64] for i in range(4)]


# matrix index of each letter key: line*8 + bit
LETTERS = {
    "A": 10, "B": 28, "C": 20, "D": 18, "E": 14, "F": 21, "G": 26, "H": 29, "I": 33,
    "J": 34, "K": 37, "L": 42, "M": 36, "N": 39, "O": 38, "P": 41, "Q": 62, "R": 17,
    "S": 13, "T": 22, "U": 30, "V": 31, "W": 9, "X": 23, "Y": 25, "Z": 12,
}


class KeyTab(unittest.TestCase):
    def setUp(self):
        self.t = tables()

    def test_sizes(self):
        self.assertEqual([len(x) for x in self.t], [64] * 4)

    def test_modifiers_and_stop_make_nothing(self):
        for t in self.t:
            for i in DEAD:
                self.assertEqual(t[i], 0xFF)

    def test_letters(self):
        norm, shift, _, ctrl = self.t
        for ch, i in LETTERS.items():
            self.assertEqual(norm[i], ord(ch), ch)
            self.assertEqual(shift[i], ord(ch) | 0x80, ch)
            self.assertEqual(ctrl[i] & 0xFF, ctrl[i])
        # CTRL-A..CTRL-Z the editor relies on: ^O (save) and ^X (quit)
        self.assertEqual(ctrl[LETTERS["O"]], 0x0F)
        self.assertEqual(ctrl[LETTERS["X"]], 0x18)

    def test_return_delete_space_cursors(self):
        norm, shift = self.t[0], self.t[1]
        self.assertEqual(norm[0], 0x14)    # DEL
        self.assertEqual(shift[0], 0x94)   # INST
        self.assertEqual(norm[1], 0x0D)    # RETURN
        self.assertEqual(norm[60], 0x20)   # SPACE
        self.assertEqual((norm[2], shift[2]), (0x1D, 0x9D))   # cursor right / left
        self.assertEqual((norm[7], shift[7]), (0x11, 0x91))   # cursor down / up
        self.assertEqual(norm[51], 0x13)   # HOME
        self.assertEqual(shift[51], 0x93)  # CLR

    def test_digits(self):
        norm = self.t[0]
        for ch, i in zip("1234567890", (56, 59, 8, 11, 16, 19, 24, 27, 32, 35)):
            self.assertEqual(norm[i], ord(ch), ch)


if __name__ == "__main__":
    unittest.main()
