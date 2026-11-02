# handoff-agent3 (Agent 3, "Kernal"), written at milestone-1 (3ff5715)

## ROLE/LANE
Kernel session, peer committer. Delivered: REU block cache, footprint pass, module loader, cbm.km, exec, @die fix, container test fanout, history scrub, milestone-1. Also main's coalescer (merge commits, leak scan, tests, push when allowed). Independent hostile review after each plan item.

## OWNS
Files: src/kernel/{jtab,proc,main,mem,exec}.s, kernel.cfg, k.inc (KSTART), blk.s (cache, sys_cache ops 0-6, su_check), src/kernel/cbm.s (resident mount/umount/diskio + cbmv stubs), src/mod/cbm.s, src/bin/{cache,mod,exec}.s, tests/test_system.py classes Cache, Pool, Modules, Exec, Drives additions. src/lib/err.s released to f7 (done). Others: uci.s and src/mod/uci.s, tools/kexports.py, mk/modules.mk, tools/ci = f7; iec.s retry fix = Agent 2.
Branches: none open. Worktree `.claude/worktrees/reu-cache` has main checked out; other agents once merged into it. Keep the rule explicit.

## STATE (done)
- milestone-1 = 3ff5715, signed annotated tag, pushed. My gates on it: container VICE 3.9 full suite 63 OK incl. keyboard+console; host 94 ok (35 skipped, need py65).
- REU cache: banks 8-10, dev 0 only, key = build id (first write per boot rewrites it) + CBM label; CACHE=0 none / 1 on / 2 cold each boot. Merged before the scrub (hashes rewritten).
- Footprint: INIT segment, CODEHI above BSS, enter + records in the $CF00 page, lib split. TPA 120 -> 153 -> 154 pages.
- Modules: loader (cx_load split, page_alloc_hi, mod_load/unload/list on SYS_CACHE 4-6, root check in su_check). cbm.km 07f6dd6. exec ab4888d. uci.km d991b1a (f7). exec sim tests 531a785. Review fixes be6b8cf. Docs refresh 8a99fd6.
- History scrub (home path in bench_basic.py; a .o with a debug path): only the range that changes was rewritten; signatures kept (110 PGP, 33 SSH Claude, 18 unsigned upstream).

## IN FLIGHT
Nothing of mine. Waiting on others: JiffyDOS-ROM set and physical-1541 boot on 3ff5715 (Agent 2; lock held for user hardware work); remote deletes (fix/iec-recover, stale branches) held for coordinator and user.

## DECISIONS HELD
- User, origin policy (docs/process.md): "Origin is a distribution channel, not authoritative. The local repository is ground truth. We choose what origin shows by force-pushing from local at will; origin is mutable and nobody relies on its history."
- User: pushes, remote deletes, tags wait for the user's go via the coordinator. Branches and merge commits to local main are free. Commits may be red; a commit records state.
- User: goal maximum TPA without cutting features, but "we don't need it": campsite cleaning. Stop point reached (154 pages, above stock BASIC 38,911 B). Coordinator: hold p_save (+6 pages idle, touches sched) and p_cwd (+2) until the user decides.
- User: stable undocumented 6510 opcodes allowed in kernel (21/21 pass on the Ultimate core); SuperCPU unsupported.
- Rejected on measurement: NBUF 6->3 (+18% block reads at prompt, +30% over 12 commands without REU, for 3 pages).
- Hygiene owner breadbin-2b (coordinator). Keymaster nibbler = imaging path; own copier shelved. GitHub purge deferred.
- Tag name milestone-1 (not m0-5, not cp1-modules). No CP2 claim: 23 pages idle, criterion 22.

## OPEN
- CP2 idle footprint 23 vs 22 pages. Owner Kernal. Next: `ps` mem column, find 1 page (sh BSS is 5 pages: ibuf/tbuf/gbuf/line; gbuf sharing rejected on lifetime, needs an sh restructure).
- JiffyDOS set + physical-1541 boot on 3ff5715. Owner Agent 2. Blocker: user hardware, lock.
- Root cause of the 1541 stall unknown; the reassembled JiffyDOS drive does not stall even without the fix (6/6 both ways).
- High region room 14 B (assert in main.s). Before any change near BSS/CODEHI: shrink BSS first.
- Warts: cbm_ensure clobbers r0; copy_args unbounded against memory the caller does not own; mod_load maps an init refusal to ENODEV; cache can confuse two disks with the same id and label written elsewhere.
- test_keyboard lost keys 2 of 20 runs (xdotool burst; Agent 2's theory).
- CP3+ (ctl syscall, CX v2, tagged allocator): CX/ABI changes need the user's go.

## FACTS NOT IN REPO
- Host VICE (macOS app): scratch HOME with config/vice, state/vice, data pre-created, -directory to the app's share/vice, `-console` for no window. SOURCING THAT ENV CHANGES HOME: a git commit in the same shell fails (gpg key not found). Commit in a clean shell.
- Container: `tools/ci/run.sh test|test-keyboard|test-only T=...` (podman machine must be up). It copies the repo at start, so editing is safe. Take `tools/with-lock` (resource vice) for VICE runs. The ultimate lock is held by Agent 2 for hardware; an image write is ~25 min.
- The Ultimate's address stays private (agent memory, never the repo). zsh: `$b:r` is a path modifier, write `${b}`. The Bash tool backgrounds commands after 120 s; Monitor expires at 30 min, re-arm. The `nice` warning is harmless.
- ca65: `@` labels are scoped by the next global label (an inserted global label breaks later `@` refs); branches across segments need `jmp`; linker symbols need `.import`. build/ is hard-coded in khash.s: BUILD= variants fail.
- git worktree add outside the repo tree is blocked by the sandbox; inside .claude/worktrees works. A branch checked out elsewhere cannot get a second worktree.
- Check signatures by the `gpgsig` header, not `%G?` (SSH-signed commits show N without a signers file).

## LESSONS (verified)
- Hostile review found a real bug every time: stale blocks after re-mounting a pristine disk (cache), a CODEHI copy that could wrap, a module run as a program repointing vectors. Run it before merge; give it spec, diff, and what was NOT run.
- My own tests were wrong twice (exec as a builtin; slot index). A failing test can be the test.
- History rewrite: scan binary blobs, not only diffs; `commit-tree -S` signs others' commits (false attribution); rewrite only the range that changes; restore original signed tags from a pristine clone.
- `git add -A` with a scratch build dir committed 233 artifacts. Ignore pattern, and `git status` before add.
- Two agents built the same module tooling at once: claim files on the board first.
- Measure before deciding (NBUF). Cache hits+misses count disk reads without hardware.

## IMPROVEMENTS
Next Kernal: review before merging, not after; one frozen tip per milestone; write the sim test with the feature; put room figures (below $CF00, above BSS) in every kernel commit message; never push or tag without the go; check `git ls-files` for artifacts before pushing.
User: faster image path (nibbler) before the next image series; split the container suite by class to run in parallel (45 min serial); standing rule that nobody checks out or merges in another's worktree; decide p_save; decide CX v2 and ABI v2.
