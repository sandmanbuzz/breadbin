# Work in progress

Rewritten 2026-10-31. For whoever picks this up next, in particular the session running next to the Ultimate. Read `CLAUDE.md` first (build, tests, test policy, standing decisions), then this. `docs/roadmap.md` has the full story list and the memory and disk-speed analyses.

## Two sessions, one repository

| Session | Where | Does |
|---|---|---|
| **Cloud session** | a cloud container, branch `claude/brave-wright-km3nrm` | The kernel: the KERNAL takeover (M0), memory layout, the filesystem interface, the UCI kernel backend. Tests under VICE. Cannot reach the Ultimate or the drives. |
| **Hardware session** | next to the C64 Ultimate and the real 1541 | Everything that needs the machine: verification, and the experiments below. It owns its own branch (`hw-bench`) and rebases it on the cloud branch. |

The hardware session is not a remote hand. It has the codebase and the machine, and it should use judgement: if an experiment shows the plan is wrong, say so in `docs/hardware-notes.md` and say what you would do instead.

## Snapshot

- **Done:** M0-1 to M0-5. The kernel owns the interrupt entry, keyboard, screen, serial bus and channels; the KERNAL ROM is not used; the BSS moved into the old ROM region, leaving 6,079 bytes of room for code (`make size`). Stage 2 of the bus driver is verified under VICE with stock and JiffyDOS ROMs, **and on your hardware** (reported: boot 75.5 s against 46.5 s for the ROM bus, since the ROM's JiffyDOS fast protocol is no longer used).
- **Next on the kernel side (cloud):** the test and size consolidation, then the filesystem interface (S6) and the UCI kernel backend (S10, S11). Disk speed is decided in `docs/roadmap.md` ("Disk speed"): the Ultimate file backend is the principal fast path; an REU block cache is the quick win; JiffyDOS and drive-side loaders are deferred.
- **Not yet done on hardware:** the physical 1541 as the boot drive, `format`, and the full M0-5 build.

## Rules of the road

- Own branch `hw-bench`, rebased on `claude/brave-wright-km3nrm` before each work package. Push it to origin.
- **You own:** `tools/ultimate*.py`, `tools/fake_ultimate.py` and its tests, any new command under `src/bin/` (the Makefile builds every `src/bin/*.s` automatically), anything under `experiments/`, and `docs/hardware-notes.md`.
- **Do not edit** `src/kernel/`, `src/lib/`, `include/breadbin.inc`, `kernel.cfg` or `k.inc`: the cloud session is working there. If you need a kernel change or a library routine, describe it in `docs/hardware-notes.md` (what, why, the smallest version) and carry on with a workaround.
- Test policy as in `CLAUDE.md`: targeted tests per package; the cloud session runs the full suite at milestones.
- ROM images and firmware stay out of the repository. The JiffyDOS images on your machine are for experiments only.
- Credit sources in the code: `fastboot1541` is by Michael Steil and asks for credit.
- Report in `docs/hardware-notes.md`: date, what you ran (a command someone else can repeat), what happened, and the commit.

## Work packages, in priority order

**WP0. Verify the current build (short).** Pull the cloud branch, `make`, boot it, and run the targeted tests from the "hardware list" in `docs/hardware-notes.md` (boot, `test_02`, `test_13`, `test_07`, `test_10`, `test_console`). The change to verify is M0-5: the kernel's tables moved to `$E000`. Record boot time. If the physical 1541 is available as device 8, repeat on it.

**WP1. A UCI explorer, as a Breadbin command.** *The most valuable package.* Write `src/bin/uci.s`: a command that talks to the Ultimate Command Interface directly (registers `$DF1B–$DF1F`; programs may touch hardware, there is no memory protection). Start with `uci id` (read `$DF1D`, expect `$C9`; send the DOS target's identify command and print the reply), then `uci ls [path]`, `uci cat file`, `uci seek`, `uci time`, and whatever else the DOS target offers (`uci/ultimate_dos_target.rst` in the documentation repository). Measure real behavior against the documentation: queue and chunk sizes, status strings, error cases, how long open, read and seek take, and the sustained read throughput on a 32 KB file in 512-byte chunks. This is the prototype for the UCI file backend (S10, S11); what you learn here is what the kernel backend is designed from, so write down every surprise. Deliverable: the command, plus a "UCI as measured" section in `docs/hardware-notes.md`. Constraint: UCI requires the "Command Interface" menu option on (it is, per your notes) and interrupts do not matter to it (polled), but keep one transaction in flight at a time.

**WP2. Fast-read feasibility (groundwork for M0-8).** Under `experiments/fastread/`, build `mist64/fastboot1541` (read its README and `pagetable.com/?p=568`), run it from the Ultimate, and find out: does it work on the emulated 1541 with the JiffyDOS ROM; with a stock ROM (the Ultimate can load a drive ROM by API, `drives/a:load_rom`; `tools/setup-vice-roms.sh` fetches one); on the physical 1541? What throughput does it reach, and does it need the screen blanked or interrupts off? Then a small variant that reads an arbitrary list of sectors, to see whether the technique serves the kernel's block reads. Deliverable: a table of drive and ROM combinations that work, speeds, and constraints, in `docs/hardware-notes.md`. Do not touch the kernel.

**WP3. Pixel-exact frames.** Start the video stream (`streams/video:start`), receive it on the test host, and write `tools/ultimate_video.py` and `UltimateTarget.screenshot(path)` (PNG via the standard library only). Read the stream format from `data_streams.rst`. Answers H9. Useful for console tests that check colour and reverse video exactly. Deliverable: the tool, a test that skips without hardware, and the format notes.

**WP4. Turbo, measured.** Through the configuration API enable the Turbo Mode setting that exposes `$D031`, then write a small command `turbo` that reads and sets the speed index and report `$D031` presence. Measure: does CPU speed change as documented (time a fixed loop against the jiffy clock)? What happens to the IEC bus driver at higher speed (expect it to break; note where), and to REU DMA and bad lines? Deliverable: the command and the measurements. No kernel changes: the kernel will switch turbo off around bus use once these are known.

When a package is done, push, and say so in `docs/hardware-notes.md`. If two or more are done and nothing new has come in, rebase and start the next one. If you are blocked on a kernel change, write it down and move on.

**WP5. Loader POC on the bench (queued, do not start until the physical-1541 stall is localised).** Only after you are confident about the bus behaviour (the physical-1541 root-mount stall, drive timing). Take Krill's Loader v194 release archive (BSD-style licence, credit "Loader by Krill"; a link is in `docs/design/fast-io.md`) and run its prebuilt `loadertest-c64.d64` unmodified from the Ultimate: (a) drive A with a stock 1541 ROM, (b) drive A with the JiffyDOS ROM, (c) on the physical 1541 with the JiffyDOS ROM, (d) with a second drive on the bus. Record: does it run; the kB/s lines it prints; whether the screen must be blank; any hang or error. The same experiment under VICE is already done (`docs/design/fast-io.md`, section 16): 6.0 to 6.4 kB/s raw on both ROM sets. A negative result on hardware is as useful as a positive one; write down *where* it fails. Do not touch the kernel for this.

## Cloud session state (written before a context compaction, 2026-10-31)

Where the cloud session stands, so a fresh context can resume:

- **Done and pushed on `claude/brave-wright-km3nrm`:** M0-1 to M0-5; real-speed keyboard tests (7 of 7 pass); the fast-I/O paper design in `docs/design/fast-io.md` (sections 1 to 16) and `docs/design/jiffydos-cleanroom.md`; the licence policy in `CLAUDE.md` (no GPL/LGPL; BSD, MIT, zlib and demoscene-norm code adoptable with credit); the REU cache requirements in `docs/roadmap.md` (switchable, never required, counted bus errors, write-through, keyed by build id).
- **Agreed order:** REU cache, then the UCI file backend, then the IEC fast paths. The hardware session keeps researching IEC with the cache off.
- **Fast-IO shortlist:** (3) clean-room JiffyDOS-class per-byte protocol behind a per-device hook in `iec.s`; (4) Krill/Bitfire-style drive loader for normal sectors with an ELoad/dotscha-style raw write plus verify. Cut: Transwarp (GPLv3), Sparkle, Spindle, DolphinDOS, cartridge loaders, MafioDOS. POC 1 done in VICE: Krill's v194 `loadertest-c64.d64` runs unmodified on stock and JiffyDOS 6.01 drive ROMs, 6.0 to 6.4 kB/s raw, 95 and 77 loop runs without errors (see section 16). The scratch script was `krillpoc.py` in the session scratchpad; it uses `tools/vicetest.py` and `BREADBIN_VICE_ARGS="-dos1541 J -dos1541II J"` with `J` the JiffyDOS drive image.
- **Not done:** the JiffyDOS-ROM disk and bus subset and the hardware run for the M0-5 milestone (the hardware session's WP0, pending the physical-1541 stall); the REU cache story; the UCI backend (design from WP1); M0-6, M0-7, M0-8.
- **Hardware session facts (from its pushed `hw-bench`, up to 62cf07c):** stage 2 boots on the Ultimate with JiffyDOS and stock ROMs; the physical 1541 stalls at the root mount in 5 of 7 boots (not yet localised, a stock-KERNAL control is running); the earlier "phantom ATN" report was retracted; turbo makes no difference; intermittent failures were traced to the harness's DMA polling. It may make kernel fixes on its own branches (such as `iec-bit-waits`) and say so in `docs/hardware-notes.md`.
- **Sources and tools (outside the repo, session scratchpad):** research reports in `research2/*.md`; clones of Bitfire (bboxy, dotscha, iszell), Sparkle2, SparkleCPP; Krill's v194 and Spindle archives extracted under `research2/x-*`; `cbmbus_doc` at `/home/user/mist64/cbmbus_doc`; open-roms (LGPL, read for understanding only, do not port) at `/home/user/mega65/open-roms`; JiffyDOS images in `jiffy/`.
- **Network:** `curl` through the proxy reaches csdb.dk, codebase64.net, pagetable.com and linusakesson.net; WebFetch still fails on some of them, and sub-agents should use Bash curl.
- **Subagent practice that worked:** Haiku agents with empty context and narrow questions plus a report template; verify their claims against sources before using them.

## Hardware session state (written before a context compaction, 2026-10-31)

**Role and branch:** hardware session, `hw-bench` (merged with the kernel branch tip `b422382`; push every time something is worth reading). Peer committer: kernel bug fixes go on `fix/<topic>` branches. Hardware runs should go through `tools/with-lock -r ultimate` (mine so far did not, nobody else was using the machine).

**Verified on the C64 Ultimate (firmware 1.1.0), see `docs/hardware-notes.md`:** REST client and harness; Breadbin boots; the stage-1 and stage-2 kernels work against the Ultimate's emulated 1541, with JiffyDOS and with stock ROMs; turbo (4 to 64 MHz) changes nothing for the disk code; no key injection exists on this product; the Ultimate's DMA reads during a disk transfer can corrupt it (poll with 1-byte reads, or not at all, while a load runs).

**Open, the one thing that matters:** the root mount stalls on the **physical 1541** (JiffyDOS 5.0 drive ROM, device 8, nothing else on the bus, 1581 removed) in most boots. Established: it is **not our `bus_acptr`** (stage 1, which uses the ROM's receive code, stalls the same way: about one boot in four or five passes either way); the drive's CLK pulse widths are normal (histogram identical to VICE and on passing boots); the stock KERNAL loads a 14 KB file 5 of 5 byte-identical and BASIC does 393 sequential and 227 random-track `U1` block reads with no stall. So the trigger is something Breadbin does or its C64 state that BASIC does not. Ruled out by experiment on the real drive: 0.8 s bit waits, a shorter receive blind window, interrupts off inside `bus_acptr`, screen blank (contaminated, untested properly), head seeks and `I0`. **In flight / queued** (branches below): a ~10 ms gap before each attention sequence (`iec-gap`, looks unhelpful: 2 of 2 stalled), interrupts off for the whole block read (`iec-irqoff`). **Not yet tried:** the REU probe and block moves ahead of the mount (kernel state differs from BASIC's), `$01 = $35` and the ROM-out memory map, the sequence of commands exactly as `blk.s` sends them (including the `cmd_status` read), a straight-line `$DD00` capture inside the transfer, `UI+` and `M-R $0023` on the physical drive.

**Why it matters for the plan:** it does not depend on which protocol the code speaks. Replacing the IEC code with a fast loader will not make it go away unless we know what triggers it; a drive-side loader runs the same drive. Settle it first or test the loader on this drive before relying on it.

**Where things are:** tools and README in `experiments/iec-stall/` (`dmaboot.py` boots a kernel image by DMA, `stockload.py` is the control, `decode.py` reads the stall dumps). Throwaway kernel experiments, all unproven, never to be merged as they are: `iec-bit-waits`, `iec-pulse-hist`, `iec-nocli`, `iec-gap`, `iec-irqoff` (each commit message says what was run). A/B method: alternate the variants on the same drive, at least five of each; one run says nothing. Config to restore after every experiment: Drive A and Software IEC enabled, `Kernal ROM = JiffyDOS-C64.bin`, turbo Off.

**For a fresh context:** `make test-host` first; the hardware needs `BREADBIN_ULTIMATE` set to the machine's address (ask the user; keep the address out of the repo); read the last four entries of `docs/hardware-notes.md`.


## Cache session state (2026-10-31, second co-agent; all co-agents are peer committers)

**Branch `reu-cache`** (worktree `.claude/worktrees/reu-cache` in the shared clone; pushed). Done: the REU block cache (see `docs/roadmap.md`, "Disk speed"), `cache` command, `make CACHE=0|1|2`, mkimage build id, `Cache` test class (9 tests; with `REU`, 10 pass under VICE with stock ROMs), an adversarial review whose BLOCK (stale blocks when a pristine image is mounted again on a warm REU) is fixed and has a regression test. Code room 5,295 bytes.

**Not run:** the JiffyDOS-ROM disk and bus subset, hardware, the full suite. Treat a hardware surprise as NEEDSFIX on this branch. **Open requests:** the hardware A/B (`CACHE=0` against `CACHE=2`, cold REU) is queued behind the regression bisect on the hardware side; `experiments/illegal-ops` PASSED on the C64 Ultimate (firmware 1.1.0, core 1.49, 21 of 21; hardware agent, 2026-10-31), so the stable undocumented opcodes are cleared for the kernel on that core.

**Decisions from the user:** undocumented (stable) 6510 opcodes are allowed in the kernel (the Ultimate core passes `experiments/illegal-ops`); SuperCPU is declared unsupported; CPU list = anything OEM-shipped, whatever upstream was tested on, and modern enthusiast hardware that is not niche. Branches may be pushed freely; nothing goes to `main` without the user.

**Next (planned, not started):** the M0-7 footprint pass: baseline `make size`, then `fs`, `cbm`, `blk` and the 1.2 KB of library per program; drive-module modularisation is the open design question (user in favour, tradeoffs first); illegal opcodes only where the byte count justifies them. Early next sprint: containerised VICE and Xvfb (`docs/roadmap.md`, "Keep the lights on").

**Known gaps:** the cache covers the boot drive only; two disks of the same build written by other machines can still look alike (the label and the per-boot id make that unlikely, not impossible); the first write of a boot costs one extra superblock write.

## Footprint pass state (2026-10-31, second co-agent; branch `footprint`, on top of `reu-cache`)

**Done and pushed (tip 05eb474):** TPA 120 -> 153 pages ($0800-$A0FF, 38 KB; was 30 KB). Where it came from: the `INIT` segment (1,140 bytes of boot-only code, released to the pool), `cbm.s` running above the BSS (`CODEHI`, 1,902 bytes), the whole syscall entry in the $CF00 page (`jsr enter` plus 3-byte address records, constant cost, ABI addresses unchanged), a split `lib.s` (programs total 73.7 -> 54.7 KB; `clear` 1,229 -> 192 bytes), plus `cld` on syscall entry. An adversarial review found no live bug; its gaps (cbm.s code never run, no process above $8000, a CODEHI copy that could wrap, a `mem_init` loop that only worked below 128 pages) are fixed and have tests (`Pool`; `Drives` run).

**Evidence:** `make test-host` 48; VICE (stock ROMs, `-console`): Pool, Drives, Persistence, Boot, Cache, REU and `test_console`, 48 pass. **Not run:** JiffyDOS ROMs, hardware, `test_keyboard`.

**Policy:** `KSTART` (`k.inc`) and `KRAM` (`kernel.cfg`) are hand-set; raise `KSTART` whenever a page is freed, keep about a page of headroom (now 236 bytes below $CF00; 183 above BSS+CODEHI, and a link-time assert guards CODEHI). Kernel growth costs TPA page for page.

**Next ideas (not started):** pg_used as an owner/class tag (breadbin-next's proposal), a lean `sys_return`, more INIT-style release of rarely used code, undocumented opcodes where they save bytes (stable set cleared on the Ultimate), driver modularisation (needs the S6 vtable first), a TPA-agnostic kernel (NTH).

## Work board (collective autonomy; nobody is in charge, everyone is in charge)

**Shared truth:** `origin/main` (merge commits welcome, red is fine: a commit records state). Branches on origin: `main` and `hw-bench` only; the old iec experiments are tags `archive/iec-*`. Work in short-lived branches (`fix/<topic>`, `feat/<topic>`), merge back with a merge commit, delete when merged. Say what was run and not run in every commit. Tell the others (SendMessage) before touching their files; the rule of thumb is "files you claimed below are yours until you release the claim". VICE runs: `tools/with-lock` or the container runner in `tools/ci` (`docs/ci.md`). Hardware needs the user's hands: do not queue anything that needs them while they are away. Nothing leaves the machine except branches and tags: no keys, addresses, hostnames.

| Lane | Who | Claims (files/areas) | Doing / next |
|---|---|---|---|
| Kernel footprint round 2 | Agent 3 (Kernal) | `src/kernel/jtab.s`, `proc.s`, `main.s`, `mem.s`, `kernel.cfg`, `k.inc`, `src/lib/*` | test fanout on main (keyboard, full suite in the container); lean `sys_return`, sched fast path, undocumented-opcode peepholes where bytes are saved |
| UCI v1 (MERGED to main 2026-11-01) | breadbin-next (f7) | new `uci.s`, `cbm.s`, `fs.s`; `blk.s` only after Agent 2's `fix/iec-recover` merges (ask first) | start from `main`; room is tight (236 bytes below $CF00): pay with `KSTART`, a page at a time, and say so |
| Hardware: IEC recovery | Agent 2 (hardware) | `fix/iec-recover`: `iec.s` (bus_acptr ready wait bounded), `blk.s` (iec_read retries); +56 bytes (180 left below $CF00 after main) | **8 of 8 boots on the physical 1541** (was about 1 in 4), `docs/hardware-notes.md`; merged to local main; next: cache A/B, JiffyDOS-ROM subset, then DMA read bit and image write-back for UCI |
| Hardware: stall bench | Agent 2 (hardware) | `hw-bench`, `experiments/iec-stall/`, `tools/ultimate*`, `docs/hardware-notes.md`, the `ultimate` lock | physical-1541 stall experiments; hardware list on main. breadbin-2b: idle, unclaimed (settled 2026-11-01) |
| CI / containers | breadbin-next (f7) authored `tools/ci` (`next/ci`) | `tools/ci`, `docs/ci.md` | container runner works for `test-host` (checked 2026-10-31); keyboard run in progress by Agent 3 |

**Open items nobody owns yet:** `test_keyboard` needs X (container); JiffyDOS-ROM disk and bus subset on main; drive-module modularisation (needs the S6 filesystem interface first); a TPA-agnostic kernel (NTH). Take one by writing your name here.

**UCI v1 merged (2026-11-01):** it spent 10 pages of TPA (`KSTART` $9700, 143 pool pages; was 153 before it) and left 310 bytes below $CF00 and 58 bytes above BSS+CODEHI. `uci.s` is throwaway-labelled: its header lists the cut list for the next footprint pass, and in v2 it becomes a loadable module (the `bmi` dispatch sites in file.s/fs.s/exec.s/cbm.s are the seam). The author's runs: Pool, Drives, Persistence, smoke, 71 host tests (23 sim tests need py65), py65 sim 23. The full suite on the merged tree is the fanout item below.

**Fanout results (Agent 3, 2026-11-01):** on `main` 4778b1a (UCI v1 merged), container (VICE 3.9): host tests 71 ok (23 skipped, need py65); full VICE suite 55 ok in 2511 s. Earlier on b9b1c9e / ca89021: keyboard 7 ok, console 6 ok (container); full suite 55 ok. Agent 2 on the JiffyDOS ROMs (VICE 3.10, JiffyDOS C64 KERNAL + 1541-II ROM): Boot + Cache + Drives, 39 ok. Hardware: physical 1541 8 of 8 boots with fix/iec-recover; cache A/B 10 of 10 at 52 s. Not run on main: the hardware list beyond those boots, anything needing the user's hands. In flight: `fix/die-deferred` (proc.s `@die` defers the exit out of the IRQ handler; Boot class running).

**TPA status (Agent 3, 2026-11-01, main ab4888d):** kernel side `KSTART` $9A00 = 146 pool pages (37,376 bytes); was 120 at the fork, 153 at the peak before UCI v1, 142 with UCI v1 plus the module loader. Done since: `cbm.km` (CBM DOS as a module loaded at the first CBM mount), the spawn/loader chain in CODEHI, `exec` (login becomes sh: login's 7 pages are free at every prompt; idle `ps` shows init 5 + sh 18 pages), `@die` deferred out of the IRQ. At idle, resident user pages are now about 23 (init 5 + sh 18) instead of about 30. Room: 159 bytes below $CF00, 75 above BSS+CODEHI. In flight: `uci.km` (f7, branch `feat/uci-km`: pool 154 pages on its own branch; waits for review and a rebase on exec), then BSS/cold-code moves from `docs/design/next/tpa-recovery.md` (items 4 to 6). Owed on main: JiffyDOS-ROM Boot/Drives and a hardware login on the exec path (Agent 2); the py65 exec error-state tests (f7, after its quota reset).

**NBUF measured, rejected (Agent 3, 2026-11-01, VICE 3.9, 2 MB REU with the cache on; block reads = cache hits + bus reads, i.e. every RAM-buffer miss, which is a bus read on a machine without a cache; same boot plus 12 shell commands):** NBUF 6: 71 at the prompt, 287 after; NBUF 4: 78 (+10%), 332 (+16%); NBUF 3: 84 (+18%), 372 (+30%). Freed BSS would be 512 / 768 bytes (2 / 3 pool pages, via code moved above the BSS). A Classic machine pays about half a second per extra read, so the cost is a slower boot and about a third more disk time per command for 2% of the pool. Kept at 6. A machine with an REU could use fewer buffers (the cache absorbs the misses) but that needs a run-time choice, not a constant. What is left in `docs/design/next/tpa-recovery.md`: item 5 (`p_save` into process pages, about 6 pages at an idle prompt, touches sched/proc_exit: heavy) and item 7 (`p_cwd`, about 2 pages, UCI paths must stay strings). The pool is 154 pages (39,424 bytes), above stock BASIC's 38,911. I would stop the TPA pass here unless the user wants item 5.
