# breadbin-next, revision 2: strategy (supersedes the ordering and several leanings in SYNTHESIS.md)

Input from the project owner after the first synthesis (2026-10-31), recorded as decisions/constraints:

- UCI v1 is a **dev unblocker**, not a ship feature: it makes effectively infinite block storage available during development as soon as a
  stable-ish version lands, and will probably be refactored when we modularize. UCI v2 is a ship milestone. UCI (and the REU) also approach
  swap / fast overlay store when present.
- The filesystem is **not committed**. The only disks in the world with c64fs are upstream's release-on-a-lark and ours; replacing it is
  merely not critical path yet. Everything is up for grabs until a stable cut.
- Contract changes are on the table with little pushback (breadbin-fork-v1 might never ship; it may be MVP-1). The relocator is welcome if
  net cheap and flexible.
- Frame the design as CP/M-like: our KERNAL replacement ~ BIOS, the OS kernel ~ BDOS. Don't be chained to it; learn from it.
  Memory allocation as a whole is the strategy question; overlays and modularization have bones in CP/M.
- `validate` risk on a Breadbin disk is accepted; a large protective directory entry is cheap if we want it.
- Process: main is sacred; the local clone is free-for-all; use worktrees; talk to co-agents; disk is source of truth. Quotas are the
  constraint; infra/tooling/non-inference resources can be asked for.

## 1. What this changes

| Was (SYNTHESIS.md) | Now |
|---|---|
| UCI = Wave 4 (after modules) | **UCI v1 = Wave 1.5, right after the syscall-page unblock.** Quick and unbeautiful is correct: resident, branch #12 on `dev_type` (about 120 B, per Lens C), run-programs-from-it (+~20 B). Pay in pool pages; do not wait for the module loader. Mark it throwaway in the file header. |
| fs v2 (F stage 3) = optional | The fs is a free variable. Decide the Classic filesystem **after** we have lived on UCI storage: what we learn about directory/inode shapes, extents, interleave and contiguous program files will be real instead of speculative. Interleave/contiguous-layout experiments cost nothing in compatibility now. |
| REU cache = a cache | REU = cache **and** overlay/swap backing store, same allocator (section 2). |
| Compatibility-conscious wording ("old binaries get ENOEXEC") | Free to break; still bump CX version so mismatches fail loudly instead of crashing. |
| `validate` listed as a hazard | Accepted. If wanted: a decoy directory entry covering the filesystem area (mkimage only). Not a priority. |
| S8 REU-resident /bin dropped | Still dropped as a boot-time copy, but "REU as overlay/swap store" stays alive. |

## 2. The memory strategy (the part worth doing first on paper)

Observation (verified, `src/kernel/mem.s`): `pg_used` is already one byte per pool page, holding 0/1. That byte can hold an owner/class tag at
**zero extra resident bytes**. One tagged page allocator then serves every consumer:

| Class | Owner field | Allocated | Reclaim |
|---|---|---|---|
| FREE | - | - | - |
| PROC | slot | from the bottom | freed on exit; swappable when a backing store exists |
| PIN (modules, RSX-like, shared lib text) | module/lib id | from the **top** | explicit unload / refcount |
| CACHE (block cache, clean overlay pages) | kind | any free page | **evictable on demand**, no write-back needed when clean |
| KERNEL (boot-time INIT, freed) | - | boot | released after boot (already done by INIT) |

Consequences (each already proposed by a lens, now one mechanism instead of five):
- Block cache buffers come from idle pages (roadmap lever 2: ~2.6 KB back) and shrink when a process needs memory.
- `exit` cleanup becomes "free every page tagged with my slot": drops `p_mpage/p_mlen` bookkeeping and makes `brk` and `exec` trivial.
- Modules load top-down, programs bottom-up (Lens C's `page_alloc_hi`) with one fragmentation story.
- Overlays are CACHE pages with a refetch recipe (file, offset): eviction is free, refetch via UCI/REU/disk.
- Swap (Expanded/Recommended only): a blocked process's PROC pages go to REU/UCI; Classic simply never swaps.
- The pool edge becomes data (`memtop`, `meminfo` extended), not a constant seen by programs.

## 3. What CP/M teaches (and where our design already echoes it)

| CP/M | Breadbin analogue | Lesson |
|---|---|---|
| One BDOS entry (call 5) with the function in C | `enter` + function code (Lens B's 5-byte table; Lens D/C's multiplexed ctl) | A single stable gateway plus a function number outlives any jump-table layout. Keep exactly one fixed address. |
| BIOS jump table + per-drive parameter blocks (DPH/DPB) | `blk.s` geometry table, the fs/char ops tables (Lens C) | Drivers behind a vector table with geometry data, not branches. |
| CCP/BDOS/BIOS relocatable to top of TPA via a BIOS base | Pool edge (`KSTART`) as a constant | Make the edge a build/boot variable (Lens A: `memtop`). |
| `.COM` at fixed 0100h; overlays done by the program itself | Page-relocated CX | We are already past `.COM`; MP/M's page-relocatable `.PRL` is essentially CX. We have the right idea. |
| CP/M 3 RSX (resident system extensions chain the BDOS) | Loadable modules / hooks | The bones of modularity: a module intercepts or extends a function range. Our module loader = CP/M 3's RSX loader, with a per-module function range in the ctl call. |
| CP/M 2.2: no loader for drivers, no overlay standard | Same gap | The gap was the lack of a standard; the module header + overlay record in CX v2 is that standard. |

## 4. Revised order

- **Wave 0 (paper + measurement, nobody blocked):** the tagged-page allocator design note; UCI measurements (Hardware, queued); Stage-0 boot read count (`make CACHE=2`, `cache stat`); interleave experiment under VICE.
- **Wave 1 (Agent 3 owns, touches jtab/main/k.inc/lib):** 5-byte entry table, lean `sys_return`, ctl multiplexer, same-process `sched` fast path, user BRK/RESTORE no longer panic, CX v2 marker.
- **Wave 1.5 (dev unblocker):** UCI v1 (transport + fs branch + programs runnable from it + `mount uci`), throwaway-labelled. The moment it works, development storage stops being the bottleneck: big sources, big assembler outputs, tools on the host side.
- **Wave 2:** tagged-page allocator (+ cache and `brk`/`exec`/`memtop` on top), CX v2 (reloc deltas, err strings out, exec past the cache), buffered stdout in lib.
- **Wave 3:** module loader + `cbm.km`, ops tables (UCI v2 as a clean module), shared library (relocation class), overlays as CACHE pages, REU as backing store.
- **Wave 4:** cooler features; filesystem decision for the Classic ship; swap; fast 1541 loader once the stall is explained.

## 5. Tooling / deployment (owner has opened the door)

Resources named: a remote runner ("effectively infinite capacity", 10GbE to a large NAS, local control; not touched in months beyond updates). Hardware stays local and dedicated; the runner needs a route to the Ultimate's network API but not to its USB/cartridge hardware.

Greenfield, in rough order of value:
1. **A `breadbin-ci` image** (cc65, Linux VICE with xvfb/xdotool, python, `c1541`; ROMs bind-mounted, never baked in). Recipe recorded in `docs/testing.md` per process.md step 5.
2. **Sharded full suite on the runner** (roadmap S4): one container per test class, each its own VICE, so the 32-minute suite becomes a few minutes and the `vice` lock mostly disappears (async resources). JiffyDOS-ROM matrix in parallel.
3. **Lease broker** (owner's idea): a tiny container holding named leases (`ultimate`, queue), `tools/with-lock` keeps its CLI. Lost state is cheap to rebuild.
4. **Build cache / artifact store on the NAS**: built `.d64` images per commit, reproducible test inputs, long-run logs.
5. Experiment spooling: unattended hardware runs queued through the broker (the stall hunt is exactly this shape).

Things I'd ask the owner for when ready: access details for the runner, a decision whether runner artifacts may live on the NAS, and a podman machine sizing (the local VM has 2 GiB / 4 CPUs).

## 6. Process notes for this branch

Reports and this synthesis live on branch `next/contract-free` in worktree `.claude/worktrees/next` (based on footprint tip a9b6acf). Local only; nothing pushed; main untouched.
