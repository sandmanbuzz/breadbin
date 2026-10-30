# Work in progress

Written 2026-10-30 for whoever picks this up next, in particular the session running next to the Ultimate. Read `CLAUDE.md` first (build, tests, standing decisions), then this. `docs/roadmap.md` has the full story list.

## Two sessions, one repository

| Session | Where | Does |
|---|---|---|
| **Cloud session** | a cloud container, branch `claude/brave-wright-km3nrm` | Kernel work, tested under VICE: the KERNAL takeover (M0), the space pass, the test harness. It cannot reach the Ultimate or the real 1541. |
| **Hardware session** | next to the Ultimate 64 and the real 1541 | Everything that needs the real machine: confirming the REST client works, running the tests on hardware, validating drivers on a real 1541, and reporting what differs from VICE. |

You are not a remote hand for the cloud session. You can read the code, change anything under `tools/`, run anything, and tell the user what you think the kernel should do. Where the cloud session is wrong about hardware, say so in `docs/hardware-notes.md`: that file is how we stay in step without chat round trips.

## Snapshot

- Last commit on the cloud branch is the one that added this file. Check `git log`.
- **Done in M0** (taking over the KERNAL so more RAM and zero page can be used): M0-1 shadow KERNAL and own vectors, M0-2 own keyboard (`src/kernel/kbd.s`), M0-3 own screen driver (`src/kernel/con.s`). The kernel no longer calls the ROM for the keyboard, the screen or interrupt entry; it still uses the ROM's IEC and file-channel routines (`blk.s`, `cbm.s`).
- **Kernel headroom:** 835 bytes below the syscall table (`make size`). That is the hard constraint on everything that follows.
- **Tests:** everything passes under VICE: host tests (45), the keyboard tests (real keystrokes), the console tests, and the system tests it touches. The full suite (about 32 minutes) was last run after M0-1 and is due after M0-4.
- **Nothing has run on hardware.** Every statement about the Ultimate comes from its documentation.

## In flight

1. **The Ultimate test bench** (this commit): `tools/ultimate.py` (REST client), `tools/fake_ultimate.py` (a fake server, for tests without hardware), `tools/ultimatetest.py` (a backend with the same interface as `tools/vicetest.py`), `tools/test_ultimate.py` (24 tests against the fake). Selected with `BREADBIN_TARGET=ultimate` and `BREADBIN_ULTIMATE=host[:port]`. **It has never talked to a real Ultimate.** Verifying it is your first job.
2. **M0-4, the IEC driver** (cloud session, next): replace the ROM's `OPEN`/`CLOSE`/`CHKIN`/`CHKOUT`/`CHRIN`/`CLRCHN`/`SETLFS`/`SETNAM` with our own bus code. It is the riskiest step and the one that most needs your real 1541: expect a request to run a specific test on it, and expect the first version to be wrong in ways VICE does not show. The kernel will also gain a second code region at `$E000–$E3FF` to make room.
3. **M0-8, fast 1541 boot and reads** (after M0-4), based on `mist64/fastboot1541`. It runs with turbo off and interrupts disabled, so it interacts with the Ultimate's turbo setting.

## What to expect over the next turns

- The kernel image changes often. Rebuild (`make`) before each hardware run, and note the commit in your notes.
- Hardware tests are a gate for M0-4 and M0-8, not for the rest of M0. Until M0-4 lands, VICE results are the reference and your results tell us where the Ultimate differs.
- Decisions in `CLAUDE.md` are standing. Raise a disagreement in `docs/hardware-notes.md` or with the user, not by working around it.

## Your first checklist

Do these in order. Put the result of each in `docs/hardware-notes.md` (it has a slot for each).

1. **Reach it.** Set `BREADBIN_ULTIMATE=<host>` (and `BREADBIN_ULTIMATE_PASSWORD` if a network password is set), then `python3 tools/ultimate.py`. It prints `/v1/info`. Record the product and firmware.
2. **Check the offline tests first:** `make test-host` (about 12 seconds). They should pass anywhere.
3. **Check the upload encoding.** The documentation does not say whether attachments are multipart or raw. Try `Ultimate(host).mount("a", image_bytes, mode="unlinked")`; if the Ultimate rejects it, try `Ultimate(host, attach="raw")`. Record which works, and fix the default in `tools/ultimate.py`.
4. **Boot Breadbin:** `python3 tools/ultimatetest.py build/breadbin.d64` should mount it, reset, load, run, and print the shell screen. Record the boot time. If it fails, look at the screen with `python3 tools/ultimate.py screen`.
5. **Run the targeted tests on hardware:** `BREADBIN_TARGET=ultimate python3 -m unittest tests.test_system.Boot.test_02_echo tests.test_system.Boot.test_13_ctrl_c_blocked_reader`, then `tests.test_keyboard` and `tests.test_console`. Record which pass, and for each failure what differed (timing, a read that returns something else, a key that did not register).
6. **Answer the open questions** in `docs/hardware-notes.md` (the key tap duration, whether a DMA read of `$0001` is meaningful, and the others).

## Working rules

- Work on your own branch (suggested: `hw-bench`), not on `claude/brave-wright-km3nrm`; the user merges, or the cloud session cherry-picks. Keep to `tools/ultimate*.py`, `tools/fake_ultimate.py`, the tests, and `docs/hardware-notes.md`. If you need a kernel change, describe it in the notes instead of making it, so the two sessions do not collide in `src/kernel/`.
- When you fix a documented-versus-real difference in the client, update `tools/fake_ultimate.py` and `tools/test_ultimate.py` to match, so the offline tests keep describing the real behavior.
- Keep ROMs and firmware images out of the repository.
