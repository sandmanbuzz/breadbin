"""chess and tetris (ported from upstream, then size-optimised) on the host under py65, through tools/asim.py:
the program's own 6502 code and library, the syscalls answered in Python. No kernel, no VICE. The expected
values were taken from the as-ported programs (the first commit of each), so an optimised build must
reproduce them exactly: same moves, same screens. `make` first; without build/ or py65 the tests skip."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT = all(os.path.exists(os.path.join(ROOT, "build", "root", "bin", p)) for p in ("chess", "tetris"))
SKIP = "py65 not installed" if asim.MPU is None else ("not built (make)" if not BUILT else None)

SAVE = "/tmp/chess.sav"
WP, WN, WB, WR, WQ, WK = 1, 2, 3, 4, 5, 6
BL = 0x80


def sq(name):
    """'e2' -> 0x88 square: rank 8 is row 0."""
    return (8 - int(name[1])) * 16 + ord(name[0]) - ord("a")


def save_file(pieces, turn=0):
    """The /tmp/chess.sav image: 128 board bytes (0x88 layout) and whose turn it is."""
    b = bytearray(129)
    for name, p in pieces.items():
        b[sq(name)] = p
    b[128] = turn
    return bytes(b)


def chess(lines, files=None):
    return asim.run("chess", [], files=files, stdin="".join(l + "\n" for l in lines).encode(), cooked=True,
                    limit=30_000_000)


def boards(out):
    """Every board printed in `out`, as 8 strings of 8 characters."""
    lines = out.decode().split("\n")
    return [["".join(x.split()[1:]) for x in lines[i:i + 8]] for i, l in enumerate(lines) if re.match(r"^8 ", l)]


def move_between(a, b):
    """'e2e4' for the one move that turns board a into board b (no castling or en passant here)."""
    gone = [(r, c) for r in range(8) for c in range(8) if a[r][c] != "." and b[r][c] == "."]
    came = [(r, c) for r in range(8) for c in range(8) if a[r][c] != b[r][c] and b[r][c] != "."]
    (r0, c0), (r1, c1) = gone[0], came[0]
    return "%s%d%s%d" % ("abcdefgh"[c0], 8 - r0, "abcdefgh"[c1], 8 - r1)


def selfplay(n):
    r = chess(["a"] * n + ["q"])
    bs = boards(r.out)
    return r, [move_between(bs[i], bs[i + 1]) for i in range(len(bs) - 1) if bs[i] != bs[i + 1]]


@unittest.skipIf(SKIP, SKIP)
class Chess(unittest.TestCase):
    def test_opening_and_the_reply(self):
        r = chess(["e2e4", "a", "q"])
        self.assertEqual(r.exit, 0)
        bs = boards(r.out)
        self.assertEqual(len(bs), 3)
        self.assertEqual(bs[0][0], "rnbqkbnr")
        self.assertEqual(bs[1][4], "....P...")
        self.assertEqual(move_between(bs[1], bs[2]), "b8a6")      # the 1-ply AI: first of the best scores

    def test_messages(self):
        out = chess(["zz", "e2e5", "e7e5", "e1e2", "q"]).out.decode()
        self.assertEqual(out.count("err: use e2e4, a, s, l, q"), 1)
        self.assertEqual(out.count("err: illegal move"), 3)       # e2e5, black's piece, a king into its own pawn

    def test_save_and_load(self):
        r = chess(["e2e4", "s", "d2d4", "l", "q"])
        out = r.out.decode()
        self.assertIn("saved /tmp/chess.sav", out)
        self.assertIn("loaded /tmp/chess.sav", out)
        self.assertEqual(len(r.files[SAVE]), 129)
        bs = boards(r.out)
        self.assertEqual(bs[-1], bs[2])                           # after `l`: the position of `s`, black to move
        self.assertIn("black (", out.rsplit("\n", 2)[-2] + out.rsplit("\n", 2)[-1])

    def test_load_without_a_file(self):
        self.assertIn("err: /tmp i/o", chess(["l", "q"]).out.decode())

    def test_fools_mate(self):
        out = chess(["f2f3", "e7e5", "g2g4", "d8h4", "a", "q"]).out.decode()
        self.assertEqual(out.count("check!"), 2)                   # once printed for the check, once in "checkmate!"
        self.assertIn("checkmate!", out)

    def test_stalemate(self):
        pos = save_file({"a8": BL | WK, "c7": WQ, "b6": WK}, turn=BL)   # black king a8, white queen c7, king b6
        out = chess(["l", "a", "q"], {SAVE: pos}).out.decode()
        self.assertIn("stalemate!", out)

    def test_a_blocked_pawn_on_its_first_rank_can_still_capture(self):
        # upstream's validate_pawn rejected every diagonal capture while the square ahead was occupied
        pos = save_file({"e2": WP, "e3": WN, "d3": BL | WP, "a1": WK, "h8": BL | WK})
        out = chess(["l", "e2d3", "q"], {SAVE: pos}).out.decode()
        self.assertNotIn("illegal", out)
        pos = save_file({"e7": BL | WP, "e6": BL | WN, "d6": WP, "a1": WK, "h8": BL | WK}, turn=BL)
        out = chess(["l", "e7d6", "q"], {SAVE: pos}).out.decode()
        self.assertNotIn("illegal", out)

    def test_promotion_makes_a_queen(self):
        pos = save_file({"a7": WP, "e1": WK, "e8": BL | WK})
        bs = boards(chess(["l", "a7a8", "q"], {SAVE: pos}).out)
        self.assertEqual(bs[-1][0][0], "Q")

    def test_a_move_that_leaves_the_king_in_check_is_refused(self):
        pos = save_file({"e1": WK, "e2": WB, "e8": BL | WR, "a8": BL | WK})
        out = chess(["l", "e2d3", "q"], {SAVE: pos}).out.decode()
        self.assertIn("err: illegal move", out)

    def test_end_of_input_ends_the_game(self):
        r = chess(["e2e4"])                                        # no `q`: stdin ends after one move
        self.assertEqual(r.exit, 0)

    def test_selfplay_is_reproduced(self):
        r, moves = selfplay(120)
        self.assertEqual(r.exit, 0)
        self.assertEqual(" ".join(moves), GOLDEN_GAME)
        self.assertEqual(boards(r.out)[-1], GOLDEN_FINAL)


def screen(out):
    """The 40x25 screen after the byte stream `out`: ESC = row+32 col+32, FF clears, LF, printable bytes."""
    scr = [[" "] * 40 for _ in range(25)]
    row = col = 0
    i = 0
    while i < len(out):
        c = out[i]
        i += 1
        if c == 12:
            scr = [[" "] * 40 for _ in range(25)]
            row = col = 0
        elif c == 27:
            assert out[i] == ord("="), "unknown escape"
            row, col = out[i + 1] - 32, out[i + 2] - 32
            i += 3
        elif c == 10:
            row, col = row + 1, 0
        else:
            scr[row][col] = chr(c)
            col += 1
    return ["".join(r).rstrip() for r in scr]


def tetris(keys=b"", jiffy0=100, **kw):
    return asim.run("tetris", [], stdin=keys, kbd=True, jiffy0=jiffy0, limit=200_000_000, **kw)


@unittest.skipIf(SKIP, SKIP)
class Tetris(unittest.TestCase):
    def test_first_screen(self):
        r = tetris(b"q")
        self.assertEqual(r.exit, 0)
        self.assertEqual(r.conmodes, [1, 0])                       # raw while playing, cooked again at the end
        s = screen(r.out)
        self.assertEqual(s[1], " " * 13 + "+----------+")
        self.assertEqual(s[2], " " * 13 + "|    @     |   SCORE: 0")
        self.assertEqual(s[22].strip(), "+----------+")
        self.assertIn("GAME OVER", s[12])                          # quit prints it too

    def test_a_piece_falls_by_itself(self):
        # 30 jiffies per step and one jiffy per idle yield: after ~65 yields the piece has moved two rows
        r = tetris(b"")
        self.assertEqual(r.exit, 0)                                # no keys: the stack tops out and the game ends
        self.assertIn("GAME OVER", "\n".join(screen(r.out)))

    def test_hard_drops_stack_and_end_the_game(self):
        r = tetris(b" " * 60)
        s = screen(r.out)
        self.assertIn("GAME OVER", "\n".join(s))

    def test_scripted_game_screens(self):
        for keys, expect in GOLDEN_TETRIS:
            with self.subTest(keys=keys):
                r = tetris(keys)
                self.assertEqual(screen(r.out), expect)


GOLDEN_GAME = (
    'a2a3 b8a6 a3a4 a8b8 a4a5 b8a8 b2b3 a8b8 b3b4 a6b4 a5a6 b7a6 '
    'a1a6 c8a6 c2c3 a6e2 f1e2 b4d5 c3c4 b8b1 c4d5 b1c1 d1c1 g8f6 '
    'c1c7 d8c7 d5d6 c7d6 d2d3 d6d3 e2d3 f6d5 d3h7 h8h7 g1e2 h7h2 '
    'h1h2 e8d8 e2d4 d8e8 d4e6 f7e6 f2f3 e8d8 f3f4 d5f4 g2g3 f4d5 '
    'h2e2 d8e8 e2e6 d7e6 g3g4 e8d7 g4g5 a7a6 g5g6 d7e8 e1d2 e8d7 '
    'd2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 '
    'd2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 '
    'd2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 '
    'd2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 '
    'd2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7 d2e1 d7e8 e1d2 e8d7'
)
GOLDEN_FINAL = ['.....b..', '...kp.p.', 'p...p.P.', '...n....', '........', '........', '...K....', '........']
# keys -> the screen when the game has ended (rows 0-24)
GOLDEN_TETRIS = [
    (b'q', [
        '',
        '             +----------+',
        '             |    @     |   SCORE: 0',
        '             |   @@@    |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             | GAME OVER|',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             |          |',
        '             +----------+',
        '',
        '',
    ]),
    (b' ', [
        '',
        '             +----------+',
        '             |     =    |   SCORE: 0',
        '             |   ===    |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |   *      |',
        '             |   ***    |',
        '             | GAME OVER|',
        '             |   ####   |',
        '             |   &&     |',
        '             |    &&    |',
        '             |     =    |',
        '             |   ===    |',
        '             |    OO    |',
        '             |    OO    |',
        '             |    @     |',
        '             |   @@@    |',
        '             +----------+',
        '',
        '',
    ]),
    (b'a', [
        '',
        '             +----------+',
        '             |          |   SCORE: 0',
        '             |     =    |',
        '             |   ===    |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |   *      |',
        '             | GAME OVER|',
        '             |   ####   |',
        '             |   ####   |',
        '             |   &&     |',
        '             |    &&    |',
        '             |     =    |',
        '             |   ===    |',
        '             |    OO    |',
        '             |   @OO    |',
        '             |  @@@     |',
        '             +----------+',
        '',
        '',
    ]),
    (b'd  ', [
        '',
        '             +----------+',
        '             |     =    |   SCORE: 0',
        '             |   ===    |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |   *      |',
        '             |   ***    |',
        '             | GAME OVER|',
        '             |   ####   |',
        '             |   &&     |',
        '             |    &&    |',
        '             |     =    |',
        '             |   ===    |',
        '             |    OO    |',
        '             |    OO    |',
        '             |     @    |',
        '             |    @@@   |',
        '             +----------+',
        '',
        '',
    ]),
    (b'w ', [
        '',
        '             +----------+',
        '             |          |   SCORE: 0',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |    %%    |',
        '             |   %%     |',
        '             |   *      |',
        '             |   ***    |',
        '             |   ####   |',
        '             | GAME OVER|',
        '             |   &&     |',
        '             |    &&    |',
        '             |     =    |',
        '             |   ===    |',
        '             |    OO    |',
        '             |    OO    |',
        '             |    @     |',
        '             |    @@    |',
        '             |    @     |',
        '             +----------+',
        '',
        '',
    ]),
]

if __name__ == "__main__":
    unittest.main()
