# breadbin-next: synthesis of lenses A-F (2026-10-31)

Sources: A process/memory, B syscall ABI, C modules/drivers, D console/cooler, E baseline, F storage/exec/boot (all in this folder).
Base code: `footprint` tip a9b6acf (pool edge $A100). Cycle counts are hand counts from listings (E), not measurements. Every
agent claim not marked here as re-checked is the agent's own VERIFIED/UNVERIFIED tag. I re-checked: 11 `dev_type` sites, `namei` root = dev 0.

## The thesis in five lines

1. Keep the process model (page-relocated CX, all resident, preemptive). Three lenses independently found the alternatives lose on a 6502.
2. The biggest waste is duplicated library: 27.5 KB of 54.7 KB `/bin` (E: 60% of image bytes; B's 47% was a source grep, use E). Fix = shared resident library + error strings out of the binaries.
3. The syscall page ($CF00) is full (E: all 32 slots used, 14 bytes spare per D). Nothing new can be added until entries are re-shaped. This gates everything.
4. Kernel bytes cost user pages 1:1 now (pool edge is a constant), so features should be modules/hooks/user programs, not resident kernel.
5. Disk/boot wins are mostly layout and format, not protocol: relocation deltas, err strings, exec bypassing the cache, interleave, REU warm boot.

## Cross-lens agreement (high confidence)

| Change | Lenses | Size of win |
|---|---|---|
| Relocations as 1-byte deltas (CX v2) | A, E, F | -4.3 KB on disk (~17 blocks); loader 49 cyc/reloc unchanged |
| Error strings out of `err.o` (read from a file on error) | E, F, B | -494 B in each of 24 programs, ~47 blocks |
| One multiplexed control syscall (`SYS_CTL`/`KCTL`/ioctl) absorbing CACHE, DISKIO, ISATTY, CONMODE | B, C, D | frees slots; 3 lenses proposed it separately |
| 5-byte `jsr enter` + `.word handler-1` table | B (peer asked) | 108+7n -> 75 cyc constant; write round trip ~250 -> ~147 (-> ~121 with lean `sys_return`) |
| `sched` skips save/restore when it picks the same process | A, E | ~6% CPU for a lone CPU-bound program (switch = 2390+19(d+d') cyc) |
| `exec` (replace image) | A, B | 7 pages back at the prompt (login stays resident behind sh today) |
| `brk` + `memtop` handed to programs | A, (S12) | unlocks edit/as/compiler sizing; pool edge no longer hard-coded in `prog.cfg` ($9000 link cap) or edit/as buffer constants |
| User BRK / bad pointer kills the process, not the machine | A, B | robustness; BRK in user code currently panics (main.s:234) |
| CX version bump to 2 | A, B, F | old binaries get ENOEXEC (exec.s:145 already checks) |

## Disagreements and open design forks (need a human)

1. **Shared library: fixed address vs relocation class.** A: resident library at $0800 with jump table, state in zero page. B: second relocation class in CX v2, library state in each program's BSS. D wants shared *program* text (vconsoles). Lean: B's relocation class for the library (no fixed-address lock-in, TPA-agnostic), fixed table only in the syscall page.
2. **Modules in the dynamic pool top (C) vs fixed window below KSTART.** C prefers pool top (counted in free_pages). Fixed window is simpler to reason about; pool top wastes nothing.
3. **UCI: `/u` mount or root?** C: `/u` first, c64fs stays root on all tiers; `namei` hard-codes dev 0 so a root switch is one variable later. F: root on UCI at Stage 4. Not in conflict if staged.
4. **Spend of kernel pages on a console demo (D, 5-6 pages) vs UCI/REU-cache needs.** Only decidable after modules exist (C stage 2-3 frees ~1.25 KB via `cbm.km`).
5. **Unverified hazard (F):** a DOS `validate` on a Breadbin disk may free every fs block. Standard DOS behaviour, unverified here. Cheap to test in VICE.

## Recommended sequence (one commit group each; dependencies in brackets)

**Wave 1: unblock (days).** One agent should own this because it all touches the $CF00 page and the interrupt path (needs full suite):
 - W1a 5-byte entry table + lean `sys_return` + CX v2 marker [B1]
 - W1b `SYS_CTL` multiplexer, absorbing CACHE/DISKIO/ISATTY/CONMODE [B, C, D]
 - W1c `sched` same-process fast path (A1); BRK/RESTORE no longer panic (A4)
 - Coordinate: Agent 3 (Kernal) has the jtab/main/kernel.cfg/k.inc/lib files; this is their area.

**Wave 2: shrink what ships (days).** [CX v2]
 - 1-byte reloc deltas; err strings to a file; exec reads past the cache (62->52 boot reads, `clear` 4->1 per F's model); `mkimage` interleave/contiguous layout experiment (Stage 0 measure first, F).
 - Library: buffered stdout in lib (B: ~540 cyc overhead per 1-byte write today), `exit` stub, stderr fd for spawn.

**Wave 3: new capabilities (1-3 weeks).**
 - `brk`/`memtop`; `exec`; `lseek` (24-bit pos already in the OFT); shared library (relocation class).
 - Module loader (`cx_load` split from `spawn_common`, ~120 B) + `/dev/zero` smoke module, then `cbm.km` as the real one (-1.25 KB net resident).
 - ops tables for fs/char devices so UCI adds no core bytes; programs runnable from non-c64fs (+20 B).

**Wave 4: cooler (needs hardware answers).**
 - Cheap/high-wow: line-editor history in `con_read` (reaches sh/basic/more/login at once), screen save/restore (`ESC S/s`), blanker (+5% CPU), per-tick user callback -> `play` (SID), `turbo` (BASIC 51x at 48 MHz per hardware-notes), `uci time`.
 - UCI backend (transport + fs module), REU warm boot via 1-2 sector first stage, compressed kernel (decompressor in INIT).
 - Medium: 2 vconsoles, REU scrollback, job control, wget/nc via UCI network target.
 - Stretch: fast 1541 loader module (waits on the stall), program overlays, swap-to-REU, soft 80-col as a user program.

## Findings that change plans already in the roadmap

- **S8 (REU-resident /bin) is redundant** with the build-id REU cache (F); drop it.
- **Roadmap says "~13 free ZP bytes"; E found 56 unreferenced** (the 7 inside the saved region + 49 at $5F-$8F). A CX v2 ZP high-mark lets the kernel save only what a program declares (-540..-1360 cyc/switch, A).
- **A 512 KB REU gets no block cache** (needs 19 banks, blk.s:21-33). Either shrink /tmp or size the cache dynamically (F).
- **`{ } ~` cannot be displayed** (con.s:348-381): blocks the S14 C-like compiler unless a RAM charset (8 pages) is added (D).
- **Every signal is fatal and there are no process groups** (proc.s:202-209): RUN/STOP kills `basic` itself. A "SIGINT catch = set flag" mode is cheap (B).
- **12-slot `wakeup` scan is 26% of a pipe byte** and 27% of the tick (E): cheap targeted win if pipes/ticks matter.
- Per-process `p_save` is 37.8% of kernel BSS (2,304 B); A2 moves it into the process's own pages (+~0.75 page/process).

## Not recommended (consistent across lenses)

Position-independent code; fixed load addresses; ZP banks per process; cooperative scheduling; program bundles; program compression now (F: ~200 resident bytes for stock-only benefit); VT100 parser, ptys, 50 Hz tick, SID/mouse as kernel devices (D); Software-IEC target (UCI DOS covers it, C); dropping the post-block status read (the stall research needs it).

## Tooling / deployment (from the user's guidance, not a lens)

- No Breadbin build image exists (podman VM up, only unrelated images). Proposal: one image with cc65, VICE (Linux arm64), xvfb, xdotool, python; ROMs mounted in, never baked in.
- `flock` across a macOS-to-VM bind mount is unreliable. Proposal (user's): a tiny broker container holding named leases (`ultimate`, optionally `vice`) with a queue; `with-lock` keeps its CLI and talks to it. State is disposable.
- Per-run containerized VICE may make the `vice` lease unnecessary (resources become async).

## Questions for humans (deduplicated)

1. Fork 1 (library mechanism) and fork 2 (module placement) above.
2. May `login` `exec` `sh`; may `SYS_CACHE`->`SYS_CTL` and `SYS_DISKIO`->`/dev/diskN` change the contract now?
3. Is the root disk allowed to need `/lib/km/cbm` to mount CBM disks?
4. Is the C-like compiler committed to braces (RAM charset dependency)?
5. Does the C64 Ultimate FW 1.1.0 expose the UCI network target? When does it write a drive-modified image back to the host file (safety of filling the REU cache over UCI)?
6. Cold-boot bus read count: ~62 (F's model) or ~120? (`make CACHE=2` then `cache stat`.)
7. Original tune for `play` in the repo, or none?

## Hardware measurement wishlist (for the hardware session, when the lock allows)

UCI: open/seek/read latency, throughput vs chunk size (256/512/4096), error cases, network target present, interrupt-on-completion available on FW 1.1.0; mounted-image write-back timing; one cold-boot bus-read count.
