"""Guard for p_save, the per-process save areas that live in the RAM under the I/O registers
(src/kernel/proc.s: p_save = $D040, 10 * SAVESZ bytes; sched and setup_proc switch $01 from $35 to
$34 around the copies). Runs the real kernel image in py65 (tools/uci_sim.py) with a memory guard
that fails on:
  (a) any read or write in $D000-$DFFF outside p_save while $01 & 7 == 4 (RAM visible: the access
      would hit RAM that is not ours instead of a VIC/SID/CIA register);
  (b) any read or write of p_save while I/O is visible ($01 & 7 >= 5: the access would hit a chip);
  (c) $01 anything but $35 on return, or the caller's interrupt flag not restored;
  (d) I clear while RAM is visible in $D000-$DFFF (an IRQ would run with I/O off).
Paths driven, from the built kernel: `sched` (save the running process, restore the next one; a
switch to a fresh process and a switch back to the same one, with I clear and I set in the caller)
and `setup_proc` (through SPAWN of /bin/echo).
Mutation tests patch the loaded image (nop an `inc $01`, a `dec $01`, the `sei`) and require the
guard to fire, so a guard that cannot fail is caught.
Limits: the simulator maps $D000-$DFFF flat apart from $D012 and the UCI registers, so this proves
the banking discipline (who touches what, with which $01 and I), not the hardware banking itself;
interrupts are not raised: instead the guard requires I set whenever RAM is visible under $D000 and
the flag restored on return. Skips without py65 or a built kernel (`make`).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import uci_sim
    from uci_sim import Sim, Mem, KernelError
except ImportError:
    uci_sim = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
BUILT = all(os.path.exists(os.path.join(BUILD, f)) for f in ("breadbin.prg", "kernel.lbl", "breadbin.d64"))
SKIP = "py65 not installed" if uci_sim is None else ("kernel not built (make)" if not BUILT else None)

MAXPROC, ZPSAVE, STKSAVE = 10, 0x3E, 128
SAVESZ = ZPSAVE + STKSAVE
P_SAVE = 0xD040
P_SAVE_END = P_SAVE + MAXPROC * SAVESZ
SP_NONE = 0
FLAG_I = 0x04


class GuardViolation(AssertionError):
    pass


class GuardMem(Mem):
    """Mem plus the $01 / $D000-$DFFF rules above. `pc` is filled in by the runner for messages."""
    guard = False
    pc = 0
    mpu = None
    in_psave_ram = 0                    # p_save accesses seen with RAM visible (the legal ones)

    def _check(self, kind, a):
        if not self.guard or not 0xD000 <= a <= 0xDFFF:
            return
        mode = self.b[1] & 7
        in_save = P_SAVE <= a < P_SAVE_END
        if mode == 4:                   # RAM visible
            if self.mpu is not None and not self.mpu.p & FLAG_I:
                raise GuardViolation("%s $%04X with RAM visible and interrupts enabled: an IRQ here "
                                     "would run with I/O off (pc ~$%04X)" % (kind, a, self.pc))
            if not in_save:
                raise GuardViolation("%s $%04X (not p_save) with $01=$%02X: RAM, not I/O (pc ~$%04X)"
                                     % (kind, a, self.b[1], self.pc))
            self.in_psave_ram += 1
        elif mode >= 5:                 # I/O visible
            if in_save:
                raise GuardViolation("%s p_save $%04X with $01=$%02X: hits a chip, not RAM (pc ~$%04X)"
                                     % (kind, a, self.b[1], self.pc))
        else:
            raise GuardViolation("%s $%04X with $01=$%02X: unexpected banking (pc ~$%04X)"
                                 % (kind, a, self.b[1], self.pc))

    def __getitem__(self, a):
        self._check("read", a)
        return Mem.__getitem__(self, a)

    def __setitem__(self, a, v):
        self._check("write", a)
        Mem.__setitem__(self, a, v)


@unittest.skipIf(SKIP, SKIP)
class PSaveGuard(unittest.TestCase):
    def setUp(self):
        self.s = Sim(None)
        s = self.s
        s.mem.__class__ = GuardMem
        s.mem.guard, s.mem.in_psave_ram, s.mem.mpu = False, 0, s.mpu
        self.m, self.L = s.mem.b, s.lbl
        self.assertEqual(self.m[1], 0x35, "the kernel boots with I/O visible")

    # ---- harness
    def run_to(self, start, until, p=0, limit=2_000_000, a=0, x=0, y=0):
        """Call `start` (JSR from the trampoline) with the P register `p`, stop at pc == until."""
        s, mpu, mem = self.s, self.s.mpu, self.s.mem
        addr = s.TRAMP
        mem.b[addr:addr + 3] = bytes([0x20, start & 0xFF, start >> 8])
        mpu.pc, mpu.sp, mpu.a, mpu.x, mpu.y, mpu.p = addr, 0xFF, a, x, y, p | 0x20
        mem.guard = True
        try:
            n = 0
            while mpu.pc != until:
                mem.pc = mpu.pc
                h = s.hooks.get(mpu.pc)
                if h:
                    h()
                    continue
                mpu.step()
                n += 1
                if n > limit:
                    raise KernelError("no return, pc $%04X" % mpu.pc)
        finally:
            mem.guard = False

    def spawn_echo(self, p=0):
        """setup_proc, for real, through SPAWN (flags 0) with the caller's P = p: fills the new slot's
        save area under the guard. Returns the slot."""
        s = self.s
        r0 = s.cstr("/bin/echo")
        self.m[2], self.m[3], self.m[4], self.m[5] = r0 & 0xFF, r0 >> 8, 0, 0
        self.run_to(s.sysno["SPAWN"], s.TRAMP + 3, p=p, a=0, x=1, y=0)
        self.assertFalse(s.mpu.p & 1, "spawn failed")
        self.assertEqual(self.m[1], 0x35)
        self.slot = self.m[self.L["sp_slot"]]
        return self.slot

    def ready_two(self):
        """Slot 0 running (cur), a second slot spawned and ready: a switch goes to the fresh process."""
        self.spawn_echo()
        self.assertEqual(self.m[self.L["p_state"] + self.slot], 1)

    def only_slot0(self):
        self.m[self.L["p_state"] + self.slot] = 0           # free: sched finds only the caller ready

    # ---- the legal paths
    def test_setup_proc_keeps_the_banking_and_the_interrupt_flag(self):
        self.spawn_echo(p=0)
        self.assertGreaterEqual(self.m and self.s.mem.in_psave_ram, ZPSAVE + 3,
                                "the guard saw the init writes to p_save")

    def test_setup_proc_restores_the_callers_i_flag(self):
        # SPAWN as a whole clears I on its own (the syscall path), so call setup_proc itself again,
        # with the sp_* state the spawn left behind, once with I clear and once with I set.
        L = self.L
        self.spawn_echo()
        for p in (0, FLAG_I):
            with self.subTest(p=p):
                self.s.mem.in_psave_ram = 0
                self.run_to(L["setup_proc"], self.s.TRAMP + 3, p=p)
                self.assertEqual(self.m[1], 0x35)
                self.assertEqual(self.s.mpu.p & FLAG_I, p, "setup_proc's plp must restore I")
                self.assertGreater(self.s.mem.in_psave_ram, ZPSAVE)

    def test_sched_switch_to_a_fresh_process_lands_on_proc_entry(self):
        L = self.L
        self.ready_two()
        self.s.mem.in_psave_ram = 0
        self.m[L["in_kernel"]] = 1
        self.run_to(L["sched"], L["proc_entry"], p=0)
        self.assertEqual(self.m[1], 0x35)
        self.assertEqual(self.m[L["cur"]], self.slot)
        self.assertNotEqual(self.s.mpu.p & FLAG_I, 0, "the new process starts with I set (saved P $04)")
        # save of slot 0: ZPSAVE + its stack; restore of slot 1: ZPSAVE + 3 stack bytes (P, ret lo/hi)
        self.assertGreaterEqual(self.s.mem.in_psave_ram, 2 * ZPSAVE + 3)

    def test_sched_back_to_the_same_process_restores_the_callers_flags(self):
        L = self.L
        for p in (0, FLAG_I):
            with self.subTest(p=p):
                self.setUp()
                self.ready_two()
                self.only_slot0()
                self.s.mem.in_psave_ram = 0
                self.m[L["in_kernel"]] = 1
                self.run_to(L["sched"], self.s.TRAMP + 3, p=p)
                self.assertEqual(self.m[1], 0x35)
                self.assertEqual(self.s.mpu.p & FLAG_I, p & FLAG_I)
                self.assertEqual(self.m[L["cur"]], 0)
                self.assertGreaterEqual(self.s.mem.in_psave_ram, 2 * ZPSAVE)

    def test_zero_page_and_stack_survive_a_round_trip(self):
        L, m = self.L, self.m
        self.ready_two()
        self.only_slot0()
        m[0x30:0x3E] = bytes(range(0x90, 0x9E))
        m[L["in_kernel"]] = 1
        self.run_to(L["sched"], self.s.TRAMP + 3, p=0)
        self.assertEqual(bytes(m[0x30:0x3E]), bytes(range(0x90, 0x9E)))

    # ---- the guard itself: a broken kernel must fail it
    def patch_window(self, fn, opcode, nth, replacement=(0xEA, 0xEA)):
        """Overwrite the nth `opcode $01` pair (dec $01 = C6 01, inc $01 = E6 01) in fn's body."""
        m, L = self.m, self.L
        a, hits = L[fn], 0
        while a < L[fn] + 0x180:
            if m[a] == opcode and m[a + 1] == 0x01:
                if hits == nth:
                    m[a:a + 2] = bytes(replacement)
                    return a
                hits += 1
            a += 1
        self.fail("no %02X 01 #%d in %s" % (opcode, nth, fn))

    def expect_guard_failure(self, setup_and_run):
        with self.assertRaises((GuardViolation, AssertionError, KernelError)) as cm:
            setup_and_run()
        return str(cm.exception)

    def test_mutation_missing_inc_after_save_loop_is_caught(self):
        self.ready_two()
        self.patch_window("sched", 0xE6, 0)            # first inc $01 (end of the save loop)
        self.m[self.L["in_kernel"]] = 1
        msg = self.expect_guard_failure(lambda: self.run_to(self.L["sched"], self.L["proc_entry"]))
        self.assertIn("$01", msg)

    def test_mutation_missing_inc_before_return_is_caught(self):
        self.ready_two()
        self.only_slot0()
        self.patch_window("sched", 0xE6, 1)            # the inc $01 before plp/rts
        self.m[self.L["in_kernel"]] = 1
        self.expect_guard_failure(
            lambda: (self.run_to(self.L["sched"], self.s.TRAMP + 3), self.assertEqual(self.m[1], 0x35)))

    def test_mutation_missing_dec_in_sched_is_caught(self):
        self.ready_two()
        self.patch_window("sched", 0xC6, 0)            # first dec $01: the save loop writes to the chips
        self.m[self.L["in_kernel"]] = 1
        msg = self.expect_guard_failure(lambda: self.run_to(self.L["sched"], self.L["proc_entry"]))
        self.assertIn("p_save", msg)

    def test_mutation_missing_dec_in_setup_proc_is_caught(self):
        self.patch_window("setup_proc", 0xC6, 0)
        msg = self.expect_guard_failure(self.spawn_echo)
        self.assertIn("p_save", msg)

    def test_mutation_missing_inc_in_setup_proc_is_caught(self):
        self.patch_window("setup_proc", 0xE6, 0)
        self.expect_guard_failure(lambda: (self.spawn_echo(), self.assertEqual(self.m[1], 0x35)))

    def test_mutation_setup_proc_without_sei_is_caught(self):
        self.spawn_echo()                              # the sp_* state setup_proc needs
        a = self.L["setup_proc"]
        while self.m[a] != 0x78:                       # the sei of `php; sei; dec $01`
            a += 1
        self.assertEqual(self.m[a + 1:a + 3], bytes([0xC6, 0x01]))
        self.m[a] = 0xEA
        msg = self.expect_guard_failure(lambda: self.run_to(self.L["setup_proc"], self.s.TRAMP + 3, p=0))
        self.assertIn("interrupts enabled", msg)

    def test_mutation_sched_without_sei_is_caught(self):
        self.ready_two()
        self.assertEqual(self.m[self.L["sched"]:self.L["sched"] + 2], bytes([0x08, 0x78]))   # php; sei
        self.m[self.L["sched"] + 1] = 0xEA
        self.m[self.L["in_kernel"]] = 1
        msg = self.expect_guard_failure(lambda: self.run_to(self.L["sched"], self.L["proc_entry"], p=0))
        self.assertIn("interrupts enabled", msg)


if __name__ == "__main__":
    unittest.main()
