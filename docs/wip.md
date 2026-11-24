# Work in progress

**Moved to the runner (2026-11).** Local `main` in the primary clone is the shared truth (origin is a stale mirror; `docs/process.md`, "Origin"); each session works in its own worktree; the roster is `fleet/roster.md` on the `fleet-store` branch. Where the text below speaks of a cloud session, `hw-bench`, origin as truth or pushing freely, it is history from before the move: check `git log` and `docs/process.md` before acting on it.

Snapshot, lanes, rules and open items refreshed 2026-11-03 to match main (45eacff) and the roster on `fleet-store`. The per-session state blocks and the first-milestone gaps are history, kept as written. Read `CLAUDE.md` first (build, tests, test policy, standing decisions), then this. `docs/roadmap.md` has the full story list and the memory and disk-speed analyses.

## Lanes now

The roster is `fleet/roster.md` on `fleet-store` (the owner's roster, published by the facilitator). Lanes are a starting point, not walls: the swarm hands work to whoever is free, and a claim is a post on the roster.

| Lane | Who | Owns |
|---|---|---|
| Facilitator | caf6de | the roster, routing, the all-stop and all-start process |
| Hygiene, process, docs | C (102763) | `main` hygiene, the docs audit, `tools/ci` sharding |
| Hardware | A (55d192) | the Ultimate, the physical 1541, `experiments/`, `tools/ultimate*`, `docs/hardware-notes.md` |
| Footprint | B (0d9a05) | kernel footprint: `jtab`, `proc`, `main`, `mem`, `kernel.cfg`, `k.inc`, `src/lib` |
| Test gates | D (5b44e6) | the VICE gates, the suite counts, the review of other lanes' work |

## Snapshot (main 45eacff, 2026-11-03)

- **Memory:** run `make size` for the room below `$CF00` and below `$FFFA`; `docs/size-ledger.tsv` has the figure per landed commit. (The 2026-11-03 figures, 445 and 44 bytes, were replaced by the ledger so they cannot go stale here.)
- **Built and on main:** M0 (own interrupt entry, keyboard, screen, serial bus and channels); the REU block cache; the footprint pass; kernel modules (the `mod` command), the CBM DOS module, UCI v1 as a module (`mount uci`), `exec`, `turbo`.
- **Hardware (Ultimate, firmware 1.1.0):** the Boot and Console subsets pass on the tip; the JiffyDOS-ROM drive set passes in the container (Boot.test_02, Drives 6 of 6). UCI measured: read and write round trips, one entry per READ DIR chunk, ABORT stops a listing after its chunk, LOAD REU at the end of 2 MB, RENAME onto an existing name answers FILE EXISTS. Full list and dates in `docs/hardware-notes.md`.
- **Physical 1541:** boots the tip image to login in 22 s (5 of 5 on 2026-11-02, after the nibbler copy of the image). The disk is not compared sector by sector: the whole-disk reader stalled four times at sector 0 (`docs/hardware-notes.md`, "four stalls").
- **Write-back:** a block written by the drive through U2 does not reach the mounted image file, in the 45 s, 300 s and drive-reset variants on a RAM-disk image (Q6, closed under those conditions).

## Branch `feat/root-eject` (single-drive swap, not landed)

`eject` / `reattach` (docs/filesystem.md): the boot disk is served from the REU cache while drive 8 holds another disk. The cache base follows `/tmp` (`rd_banks`: top 3 banks, so 256 KB and 512 KB REUs have a cache). Resident cost: the writer gate (`rgate`, kind in each syscall record's third byte; a `jsr` in `enter` while `ejected`), a 3-byte `ejv` stub and the mount remap; the ops are `eject.km`. Writers to `/` sleep on `CH_ROOT` until `reattach`. Tests: `Eject`, `Cache`.

## Rules of the road

- Local `main` in the primary clone is the shared truth. Origin is a mirror and out of scope for now; a push waits for the user's go (`docs/process.md`).
- Each session works in its own worktree. Land work on local `main` under the land lock (`tools/with-lock -r land -- ...`), and say what was run and not run in the commit message.
- A commit records state, not success: red is fine when it is what you are working on.
- Emulator runs go through `tools/ci/run.sh`; timing runs take every slot with `BREADBIN_CI_EXCLUSIVE=1`. Hardware runs take `tools/with-lock -r ultimate -- ...`, announce the write first, restore the configuration by trap, and read it back.
- Post claims, results and blocks on the roster. Re-read the `fleet-store` tip before a roster write, and base the write on that tip.

## Open items

- **Story: `test_tab_no_match_does_not_fire` (keyboard test, red on main; owner-promoted from known issue to a story, 2026-11-07).** It fails in its setUp, in the full suite and in targeted runs, on stock and JiffyDOS ROMs; cause not identified (repro and what was tried: `docs/testing.md`, "Known issues"). Done when: the cause is named, the test passes in the full VICE suite, and the test's positive control shows Return ran. It is a broken stair, not an accepted limit: it stays red in every release note until fixed.
- **Backlog (owner, 2026-11-07; solvable): the primary checkout is too easy to move, and tools break when it is.** Scope: make `tools/land.sh` and the quota tools (`tools/claude-quota`, `tools/install-quota-timer.sh`, the systemd units) work without depending on where the primary clone sits or which branch it is on. No code now. Finding checked on main `00e7338`: `tools/quota-status` and `tools/quota-rate` are not files; they are the names of the branches that carried the status and burn-rate work, now merged. The one tool is `tools/claude-quota` (`status` reports the burn rate and the suggested tier), and it is on main, so a reading that fell back to the raw tool is a naming mix-up, not a missing file. The real dependency to remove: the timer unit runs `tools/claude-quota` from the primary clone's path, so moving the clone breaks the poller. Done when: land and the poller run from any path and branch, and a test moves a clone and runs both.
- **CP2 (footprint): closed.** The owner accepted CP2 as it stands on main: an idle prompt holds 21 pool pages, inside the 22-page criterion. The branch `feat/cp2-sh-bss` at 6a99281 (the 20-page `sh` buffer change) stays unmerged. Figures (R17, 2026-11-04, clean clone of main `ba69ca4`, VICE stock ROMs): an idle prompt holds **21 pool pages** on main and **20** with the CP2 `sh` buffer change (`pg_used` count, `KSTART` `$A200`, 154 pool pages). `free` shows 6 K used on main and 5 K with the change. Room below `$CF00` is 361 bytes and above the BSS 14 bytes on main, unchanged by the CP2 change (its `sh` is 128 bytes less BSS, no CX-size change: `sh` is 3,682 bytes either way). The 22-page criterion in `docs/design/next/checkpoints.md` is met by 21 on main; the owner accepted this as CP2's exit.
- **Backlog (driver, `tools/ci/sharded.sh`): the driver can exit before its shards clean up.** `stop_all` (Ctrl-C, TERM, HUP) signals each shard's subshell directly, so the driver's `wait` can return while a shard's `run.sh` is still handling TERM and removing its container. Observed: not in 25 runs of the ctrl-c test; a probe found all six stubs stopped 0.16 s after driver exit. The test (`tools/test_shards.py`) now polls for the stopped count (9d4edb7). Not changed in the driver; fix when the driver is next touched: let each subshell finish its own cleanup and wait for it, rather than killing the subshell.
- **Physical-disk compare:** parked. The reader stalls before the first status byte of the first U1; its code and state are intact. The cause is not known. The read-back that exists (`mcdup` with read-back) rewrites every sector and is the owner's call.
- **UCI:** the disk-full case (Q4) and Q9 (turbo with UCI, low priority) are open. Disk-full is the owner's to run.
- **Drives split by method:** done and landed (`782fbdf`, six shards, `tools/ci/shards.txt`); the sharded VICE series on it was green three times (see `docs/ci.md`). Nothing open on this lane.
- **Size ledger:** `tools/size_ledger.py` and `docs/size-ledger.tsv` are on main (9353b44); `CLAUDE.md`'s status points at the ledger.
- **Tests:** `test_keyboard` needs X (container); the JiffyDOS-ROM subset is partly run (above).
- **Roster:** `fleet/missing.md` has no writer yet.
- **Origin and pushes:** the user's decision. Decided: push at first numbered release

## Cloud session state (written before a context compaction, 2026-10-31)

Where the cloud session stands, so a fresh context can resume:

- **Done and pushed on `claude/brave-wright-km3nrm`:** M0-1 to M0-5; real-speed keyboard tests (7 of 7 pass); the fast-I/O paper design in `docs/design/fast-io.md` (sections 1 to 16) and `docs/design/jiffydos-cleanroom.md`; the licence policy in `CLAUDE.md` (no GPL/LGPL; BSD, MIT, zlib and demoscene-norm code adoptable with credit); the REU cache requirements in `docs/roadmap.md` (switchable, never required, counted bus errors, write-through, keyed by build id).
- **Agreed order:** REU cache, then the UCI file backend, then the IEC fast paths. The hardware session keeps researching IEC with the cache off.
- **Fast-IO shortlist:** (3) clean-room JiffyDOS-class per-byte protocol behind a per-device hook in `iec.s`; (4) Krill/Bitfire-style drive loader for normal sectors with an ELoad/dotscha-style raw write plus verify. Cut: Transwarp (GPLv3), Sparkle, Spindle, DolphinDOS, cartridge loaders, MafioDOS. POC 1 done in VICE: Krill's v194 `loadertest-c64.d64` runs unmodified on stock and JiffyDOS 6.01 drive ROMs, 6.0 to 6.4 kB/s raw, 95 and 77 loop runs without errors (see section 16). The scratch script was `krillpoc.py` in the session scratchpad; it uses `tools/vicetest.py` and `BREADBIN_VICE_ARGS="-dos1541 J -dos1541II J"` with `J` the JiffyDOS drive image.
- **Not done:** the JiffyDOS-ROM disk and bus subset and the hardware run for the M0-5 milestone (the hardware session's WP0, pending the physical-1541 stall); the REU cache story; the UCI backend (design from WP1); M0-6, M0-7, M0-8.
- **Hardware session facts (from its pushed `hw-bench`, up to 62cf07c):** stage 2 boots on the Ultimate with JiffyDOS and stock ROMs; the physical 1541 stalls at the root mount in 5 of 7 boots (not yet localised, a stock-KERNAL control is running); the earlier "phantom ATN" report was retracted; turbo makes no difference; intermittent failures were traced to the harness's DMA polling. It may make kernel fixes on its own branches (such as `iec-bit-waits`) and say so in `docs/hardware-notes.md`.
- **Sources and tools (outside the repo, session scratchpad):** research reports in `research2/*.md`; clones of Bitfire (bboxy, dotscha, iszell), Sparkle2, SparkleCPP; Krill's v194 and Spindle archives extracted under `research2/x-*`; `cbmbus_doc` and open-roms (LGPL, read for understanding only, do not port), cloud-container paths that are gone; JiffyDOS images in `jiffy/`.
- **Network (cloud container, 2026-10-31):** `curl` through the proxy reaches csdb.dk, codebase64.net, pagetable.com and linusakesson.net; WebFetch still fails on some of them, and sub-agents should use Bash curl.
- **Subagent practice that worked:** Haiku agents with empty context and narrow questions plus a report template; verify their claims against sources before using them.

## Hardware session state (written before a context compaction, 2026-10-31)

**Role and branch:** hardware session, `hw-bench` (merged with the kernel branch tip `b422382`; push every time something is worth reading). Peer committer: kernel bug fixes go on `fix/<topic>` branches. Hardware runs go through `tools/with-lock -r ultimate`.

**Verified on the C64 Ultimate (firmware 1.1.0), see `docs/hardware-notes.md`:** REST client and harness; Breadbin boots; the stage-1 and stage-2 kernels work against the Ultimate's emulated 1541, with JiffyDOS and with stock ROMs; turbo (4 to 64 MHz) changes nothing for the disk code; no key injection exists on this product; the Ultimate's DMA reads during a disk transfer can corrupt it (poll with 1-byte reads, or not at all, while a load runs).

**Open, the one thing that matters:** the root mount stalls on the **physical 1541** (JiffyDOS 5.0 drive ROM, device 8, nothing else on the bus, 1581 removed) in most boots. Established: it is **not our `bus_acptr`** (stage 1, which uses the ROM's receive code, stalls the same way: about one boot in four or five passes either way); the drive's CLK pulse widths are normal (histogram identical to VICE and on passing boots); the stock KERNAL loads a 14 KB file 5 of 5 byte-identical and BASIC does 393 sequential and 227 random-track `U1` block reads with no stall. So the trigger is something Breadbin does or its C64 state that BASIC does not. Ruled out by experiment on the real drive: 0.8 s bit waits, a shorter receive blind window, interrupts off inside `bus_acptr`, screen blank (contaminated, untested properly), head seeks and `I0`. **In flight / queued** (branches below): a ~10 ms gap before each attention sequence (`iec-gap`, looks unhelpful: 2 of 2 stalled), interrupts off for the whole block read (`iec-irqoff`). **Not yet tried:** the REU probe and block moves ahead of the mount (kernel state differs from BASIC's), `$01 = $35` and the ROM-out memory map, the sequence of commands exactly as `blk.s` sends them (including the `cmd_status` read), a straight-line `$DD00` capture inside the transfer, `UI+` and `M-R $0023` on the physical drive.

**Why it matters for the plan:** it does not depend on which protocol the code speaks. Replacing the IEC code with a fast loader will not make it go away unless we know what triggers it; a drive-side loader runs the same drive. Settle it first or test the loader on this drive before relying on it.

**Where things are:** tools and README in `experiments/iec-stall/` (`dmaboot.py` boots a kernel image by DMA, `stockload.py` is the control, `decode.py` reads the stall dumps). Throwaway kernel experiments, all unproven, never to be merged as they are: `iec-bit-waits`, `iec-pulse-hist`, `iec-nocli`, `iec-gap`, `iec-irqoff` (each commit message says what was run). A/B method: alternate the variants on the same drive, at least five of each; one run says nothing. Config to restore after every experiment: Drive A and Software IEC enabled, `Kernal ROM = JiffyDOS-C64.bin`, turbo Off.

**For a fresh context:** `make test-host` first; the hardware needs `BREADBIN_ULTIMATE` set to the machine's address (ask the user; keep the address out of the repo); read the last four entries of `docs/hardware-notes.md`.


## Cache session state (2026-10-31, second co-agent; all co-agents are peer committers)

**Branch `reu-cache`** (worktree `.claude/worktrees/reu-cache` in the shared clone; pushed). Done: the REU block cache (see `docs/roadmap.md`, "Disk speed"), `cache` command, `make CACHE=0|1|2`, mkimage build id, `Cache` test class (9 tests; with `REU`, 10 pass under VICE with stock ROMs), an adversarial review whose BLOCK (stale blocks when a pristine image is mounted again on a warm REU) is fixed and has a regression test. Code room 5,295 bytes.

**Not run:** the JiffyDOS-ROM disk and bus subset, hardware, the full suite. Treat a hardware surprise as NEEDSFIX on this branch. **Open requests:** the hardware A/B (`CACHE=0` against `CACHE=2`, cold REU) is queued behind the regression bisect on the hardware side; `experiments/illegal-ops` PASSED on the C64 Ultimate (firmware 1.1.0, core 1.49, 21 of 21; hardware agent, 2026-10-31), so the stable undocumented opcodes are cleared for the kernel on that core.

**Decisions from the user:** undocumented (stable) 6510 opcodes are allowed in the kernel (the Ultimate core passes `experiments/illegal-ops`); SuperCPU is declared unsupported; CPU list = anything OEM-shipped, whatever upstream was tested on, and modern enthusiast hardware that is not niche. Pushes wait for the user's go (`docs/process.md`, "Origin"); everyone lands on local `main`, red is fine.

**Next (planned, not started):** the M0-7 footprint pass: baseline `make size`, then `fs`, `cbm`, `blk` and the 1.2 KB of library per program; drive-module modularisation is the open design question (user in favour, tradeoffs first); illegal opcodes only where the byte count justifies them. Containerised VICE and Xvfb are done (`tools/ci`, `docs/ci.md`).

**Known gaps:** the cache covers the boot drive only; two disks of the same build written by other machines can still look alike (the label and the per-boot id make that unlikely, not impossible); the first write of a boot costs one extra superblock write.

## Footprint pass state (2026-10-31, second co-agent; branch `footprint`, on top of `reu-cache`)

**Done and pushed (tip 05eb474):** TPA 120 -> 153 pages ($0800-$A0FF, 38 KB; was 30 KB). Where it came from: the `INIT` segment (1,140 bytes of boot-only code, released to the pool), `cbm.s` running above the BSS (`CODEHI`, 1,902 bytes), the whole syscall entry in the $CF00 page (`jsr enter` plus 3-byte address records, constant cost, ABI addresses unchanged), a split `lib.s` (programs total 73.7 -> 54.7 KB; `clear` 1,229 -> 192 bytes), plus `cld` on syscall entry. An adversarial review found no live bug; its gaps (cbm.s code never run, no process above $8000, a CODEHI copy that could wrap, a `mem_init` loop that only worked below 128 pages) are fixed and have tests (`Pool`; `Drives` run).

**Evidence:** `make test-host` 48; VICE (stock ROMs, `-console`): Pool, Drives, Persistence, Boot, Cache, REU and `test_console`, 48 pass. **Not run:** JiffyDOS ROMs, hardware, `test_keyboard`.

**Policy:** `KSTART` (`k.inc`) and `KRAM` (`kernel.cfg`) are hand-set; raise `KSTART` whenever a page is freed, keep about a page of headroom (`make size` and `docs/size-ledger.tsv` have the current figures; a link-time assert guards CODEHI). Kernel growth costs TPA page for page.

**Next ideas (not started):** pg_used as an owner/class tag (breadbin-next's proposal), a lean `sys_return`, more INIT-style release of rarely used code, undocumented opcodes where they save bytes (stable set cleared on the Ultimate), driver modularisation (needs the S6 vtable first), a TPA-agnostic kernel (NTH).

## Work board

Replaced by the roster: `fleet/roster.md` on `fleet-store`. Claims, results and blocks go there, not here.

## Known gaps at the first milestone (Agent 3, 2026-11-01; these are declared, not hidden)

- **Physical-1541 stall:** mitigated (bounded `bus_acptr` wait ~2 s, `iec_read` retried 3x with UNTALK), 13 of 13 boots; root cause unknown. Agent 2's JiffyDOS-drive A/B (with and without the mitigation) is the open test.
- **REU cache:** two disks written elsewhere with the same build id and label can be confused if they alternate on one REU; the first write of a boot costs one extra superblock write.
- **High region room is 44 bytes** (above the BSS and `CODEHI`, up to `$FFFA`): any change near it fails the `.assert` in `main.s`. Procedure: shrink BSS or move code out first; do not raise the assert.
- **Modules are a cooperative trust model:** no file owners or modes, no memory protection (`docs/design/next/modules-v1.md`, "Security model").
- **Wart list:** the mount call clobbers the caller's first argument register; the argument copier has an inherited bound hole (needs memory the caller does not own); `mod_load` maps a refused `init` to ENODEV.
- **Tests:** `test_keyboard` sends real X key events in bursts and has lost keys twice in about 20 runs on one host; hardware coverage of the final tip is Agent 2's series.
- **Decided 2026-11-16 (owner):** `p_save` goes in the RAM under I/O at `$D040-$D7AB` (copied with interrupts off and `$01` = `$34`; branch `feat/psave-io`), and cold code moves to `CODEHI`; the gain is kept as **kernel room** for the landings that need it (JiffyDOS, format 2), not turned into pool pages. The pool stays 155 pages; `KSTART` can move up later, one constant, once the pieces are in and measured. `$D000-$D03F` and `$D7AC-$DFFF` stay free. Still held: `p_save` into process pages, `p_cwd` as an inode (about 2 pages). Intended later: a dedicated size pass in the demoscene style (research first).
- **2026-11-18, `size/research` (landed 9ad872b; hardware steps 1-5 run, one unexplained init panic in 23 boots, docs/hardware-notes.md):** the size pass's first structural round (S1-S5 in `docs/design/size-spike.md`): `p_save` becomes a page per slot at `$D000 + slot*256` that also holds the cwd and the name (`p_cwd`, `p_name` leave the BSS); 725 bytes of kernel room against `main` after its MAXPROC 8 merge (low 1149 -> 1271, high 687 -> 1290), the pool still 155 pages; the `$CF00` page is full.
- **Fleet-level item, from the user:** the physical-1541 image write takes about 25 minutes and holds the `ultimate` lock for all of it. A faster write path (a drive-side fast loader, or writing only the changed sectors) would cut task latency and lock hold time for everyone; do it before the next major series of image writes.
- **Origin:** declared 2026-11-01, `docs/process.md`, "Origin" (a mirror; history on GitHub is mutable and can be force-pushed).

## Owner decisions (2026-11-06 retro)

Owner decisions live in this section; the facilitator is the single pane of glass for them.

- `fleet-store` is the canonical ground truth: "if it ain't there it ain't true". Branch state is tracked there.
- DONE-DONE includes the owning agent's cleanup after a task.
- `tools/land.sh` improvements approved: when it refuses on a dirty primary tree, name the dirty file and its owner.
- `make` is the `test-host` backstop: `test-host` must build first.
- Footprint: Level 1 approved, Level 2 kept on the table, Level 3 deferred to a corner.
- NBUF experiment approved as a build constant; a perf study is on the roadmap as a nice-to-have.
- Size ledger: one row per landing.
- The demo runner may be asked for detail when a change could show in a demo.

## Branch state (sprint 2026-11-06)

From `git branch -a --merged main` / `--no-merged main` on 2026-11-06 (dates are last commit). `fleet-store` is the canonical record; this table is a snapshot. Nothing was deleted.

| branch | state | owner | note |
|---|---|---|---|
| fix/create-probe | landed | C | merged 2026-11-03 |
| feat/footprint-b-save-jtab | landed | B | merged 2026-11-03 |
| notes/hw-agent-a, notes/stats-correction | landed | A, D | merged 2026-11-02 |
| worktree-bridge-cse_01K1DnUTJ6dVBi4ux4XrSh9C | landed | facilitator | merged 2026-11-04 (empty `tests/__init__.py`) |
| feat/size-ledger | landed | C | merged 2026-11-03 |
| other fix/*, feat/*, docs/*, tools/*, test/*, port/*, space/*, chore/*, archive/*, older worktree-* | landed | various | all in `--merged main`; no action |
| archive/fix-create-entry-first | stale | C | renamed from fix/create-entry-first; kept as an archive |
| feat/cp2-sh-bss | held | B | docs say it stays unmerged (2026-11-02) |
| feat/brk-kill | held | D | out of the coalesce (2026-11-06) |
| tools/shards-balance2 | stale | C | conflicts with the balance3 layout; drop |
| wip/nf-unfixed-arm | unmerged | - | DELETE CANDIDATE for the owner (2026-11-02) |
| fleet/roster-agent-* (b, b-2..b-7, c, c-2..c-5) | unmerged | facilitator | DELETE CANDIDATES for the owner; roster lives on `fleet-store` |
| fleet/handoff-agent-b, fleet/handoff-agent-c, fleet/luggage-agent-a, wip/agent-d-pack | unmerged | agents b, c, a, d | not classified by the owner; review before any cleanup |
| fleet-store | in flight | facilitator | canonical roster and branch state |
| up/*, upstream/fix-webdemo-cache | in flight | upstream | upstream contributors' refs; not ours to merge or delete |

## Hater Review Request (2026-11-16)
- **From:** P1 slice 1 author
- **To:** Agent C
- **What:** Hater review of feat/p1-slice1-status (b57f83b)
- **Spec:** docs/design/hater-p1-slice1.md
- **Branch:** feat/p1-slice1-status (pushed to origin)
- **Reviewer branch:** feat/p1-slice1-status-hater-review
- **Key concerns:** 
  1. Short-circuit logic for && and || (stage_stop handling)
  2. $? expansion correctness (dec_str integration)
  3. Token boundary handling in stage loop
  4. SYS_WAIT exit code capture (stx vs sta)
  5. Host sim WAIT return value modeling
- **Not run:** VICE end-to-end, JiffyDOS-ROM, hardware

## Hater Review Round 2 (2026-11-16)
- C agent responded with P1 findings:
  1. abort() doesn't set last_status on redirect/pipe failures
  2. stage_stop is dead code (written but never read)
  3. Design doc still says VICE tests not run
- All three fixed and pushed (1d48353)
- Waiting for final verdict

## L3 compile-to-file (B1 to B3), feat/bas-crush, 2026-11-24

`bas` BUILD writes a `.bx` file; `brun` runs it (basic.md 6.1). Gate at 33c80dd (code as at 908d465): full sharded suite with stock ROMs 168 of 168 (s5 25 of 25), with JiffyDOS ROMs 168 of 168 (14 skips by design), smoke 4 of 4 (the Ctrl-C test fails only when started with SIGINT ignored, e.g. a shell `&`), host py65 153 OK. Hardware (Ultimate, drive A on bus 9): the BUILD-then-brun test, `Basic.test_hello`, `CompiledC` and `SharedVM` pass; `SharedVM` failed once on a stray `[12] done` job line and passed on rerun, `test_hello` once on an HTTP timeout. The harness leaves drive A on `/Temp/t_pvm.d64`; it was remounted on `/Temp/test.d64` (mode `unlinked`).
Hater gate found, fixed in 908d465: reloc walked an `x LDK`'s 4 constant bytes as code; brun's size check wrapped at 16 bits; BUILD ignored write errors. Accepted, not fixed: a corrupt `.bx` can still point variable and call offsets anywhere (the VM has no sandbox); `rtid` is a sum of sizes (the host layout test compares labels); LEAVE trusts frame byte 0; no +-127/-128 branch edge tests. `bas` is 9,209 B with BSS: 36 pages, 7 B to spare. Next: B4 manual page, then L3d.
