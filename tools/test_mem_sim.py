"""The page allocator (src/kernel/mem.s) in the real kernel under py65, against a model.

page_alloc is first fit from the bottom of the pool; page_alloc_hi is first fit from the top
(the first n free pages in a row met going down, the lowest of them returned). Both return
A = the run's first page with carry clear, or carry set and A = ENOMEM; on success X is the
run's first index + n and Y is 0. A random walk of allocations and frees checks the kernel
against that model, pg_used and free_pages included.
Skips when py65 is missing or the kernel is not built (`make`).
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import uci_sim
    from uci_sim import Sim
except ImportError:
    uci_sim = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)
POOL_FIRST = 8
ENOMEM = 12                    # include/breadbin.inc


def model_alloc(used, n, top):
    order = range(len(used) - 1, -1, -1) if top else range(len(used))
    run = []
    for i in order:
        if used[i]:
            run = []
            continue
        run.append(i)
        if len(run) == n:
            return min(run)
    return None


@unittest.skipIf(SKIP, SKIP)
class PageAlloc(unittest.TestCase):
    def setUp(self):
        self.s = Sim(None)
        L = self.s.lbl
        self.base = L["pg_used"]
        self.npool = L["free_pages"] - L["pg_used"]          # free_pages follows pg_used
        m = self.s.mem.b
        for i in range(self.npool):                             # start from an empty pool
            m[self.base + i] = 0
        m[L["free_pages"]] = self.npool

    def call(self, name, a=0, x=0, y=0):
        return self.s.call(name, a, x, y)

    def check_pool(self, used):
        m = self.s.mem.b
        self.assertEqual([m[self.base + i] for i in range(self.npool)], [1 if u else 0 for u in used])
        self.assertEqual(m[self.s.lbl["free_pages"]], used.count(False))

    def test_random_walk_matches_the_model(self):
        rnd = random.Random(1541)
        used = [False] * self.npool
        held = []
        for step in range(1500):
            if held and rnd.random() < 0.45:
                first, n = held.pop(rnd.randrange(len(held)))
                self.call("page_free", a=first + POOL_FIRST, y=n)
                for i in range(first, first + n):
                    used[i] = False
            else:
                n = rnd.choice((1, 1, 2, 3, 5, 8, 20, 40))
                top = rnd.random() < 0.5
                want = model_alloc(used, n, top)
                c, a, x, y = self.call("page_alloc_hi" if top else "page_alloc", y=n)
                if want is None:
                    self.assertTrue(c, f"step {step}: {n} pages fitted where the model has none")
                    self.assertEqual(a, ENOMEM)
                else:
                    self.assertFalse(c, f"step {step}: {n} pages, top={top}: ENOMEM, model {want}")
                    self.assertEqual(a, want + POOL_FIRST, f"step {step}: n={n} top={top}")
                    self.assertEqual((x, y), (want + n, 0))
                    for i in range(want, want + n):
                        used[i] = True
                    held.append((want, n))
            self.check_pool(used)

    def test_edges(self):
        used = [False] * self.npool
        c, a, *_ = self.call("page_alloc", y=0)
        self.assertTrue(c, "zero pages must fail")
        c, a, *_ = self.call("page_alloc_hi", y=self.npool)
        self.assertEqual((c, a), (False, POOL_FIRST), "the whole pool from the top")
        c, *_ = self.call("page_alloc", y=1)
        self.assertTrue(c, "a full pool")
        self.call("page_free", a=POOL_FIRST, y=self.npool)
        c, a, *_ = self.call("page_alloc_hi", y=1)
        self.assertEqual(a, POOL_FIRST + self.npool - 1, "the top page")
        c, a, *_ = self.call("page_alloc", y=1)
        self.assertEqual(a, POOL_FIRST, "the bottom page")
        used[0] = used[-1] = True
        self.check_pool(used)


if __name__ == "__main__":
    unittest.main()
