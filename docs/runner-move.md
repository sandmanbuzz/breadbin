# Moving the fleet to the runner

Status: soft prep. No date is set; the user calls the all-stop when the world is quiet. This is the plan for the pack, the copy and the unpack, and the tools that exist for it. Nothing here is verified on the runner yet: every "check" below is a thing to run there, not a thing that has passed.

Decided by the user: the whole operation moves, authoritative clone included; the old clone is retired (copied byte for byte to different disk, never shared inodes, the archive kept); sessions do not carry over (new, empty sessions unpack from the repo and the luggage); containers are the only toolchain; the fleet gets one CCD of the runner. The runner is on the same LAN as the Ultimate, so hardware moves with it. No host names, addresses or user names go in this repo: write `$RUNNER` and `~/`.

## Tools (landed ahead of the move)

- `tools/readiness`: read-only. Lists what stops a clean stop or copy (uncommitted tracked changes, an interrupted merge/rebase/revert, a detached worktree whose commits are on no branch, a held lock, a running VICE or container, a broken `git fsck`) and prints a RECORD (tips and a digest of every ref) to compare after the copy.
- `tools/ci/run.sh`: the one way to run the toolchain and VICE. Takes a VICE slot only for targets that start VICE (`test-host`, `size`, `all`, `clean` take none). `BREADBIN_CI_EXCLUSIVE=1` takes every slot. `BREADBIN_CI_JIFFY=<dir>` mounts the JiffyDOS ROMs and wires them into VICE (not yet run: see step 0).
- `tools/ci/Containerfile`: cc65, VICE, xdotool, python3 and make are pinned. Measured on the arm64 image against the host build (cc65 2.18): `make size` identical and `build/breadbin.d64` identical, so the toolchain gap is nil today. Expected on x86_64 too; check it (step 0).

## Pack (before the all-stop)

Rule: if it can be written down, commit it (branch `fleet-store`, your handoff file). The luggage is only what cannot be committed.

Each agent, in this order:

1. Commit everything on a branch, red is fine. Detached worktrees: put the commit on a `wip/<name>` branch. `tools/readiness` must show nothing in your worktrees.
2. Update your handoff on `fleet-store`: lane, state, open asks (who you asked, what, when), approvals the user gave you that are not yet used (they do not carry to a new session: a peer's relay is not an approval, and the user's word to the old session is gone), and the next three things you would do.
3. Release your lock, stop your containers and VICE.
4. Luggage manifest in `fleet-store`, one line per item: path, why it is needed, secret yes/no. Typical items: the JiffyDOS ROM directory, scratch outputs worth keeping (maps, timing logs), your session transcript (read-only reference: a compaction summary cites it, and it is the one thing a replacement cannot reconstruct).
5. Say "packed" to the facilitator with the tip of main you saw.

The user, not the agents, packs what is secret or machine-level: `gh` auth for the public identity, the signing key (carry it or mint a new one: a new one changes the public identity, so it is the user's decision), the global `CLAUDE.md`, the per-project memory directory, settings and the permission allowlist (rewrite any absolute path), the ROM cache. Encrypt the luggage archive in transit; delete it after the unpack.

Go/no-go for the all-stop (the "bad point in time" test): `tools/readiness` is READY in the primary clone and every worktree; no full-suite or JiffyDOS gate in flight (about 42 minutes; a half run tells nothing); no hardware write in flight (the 1541 image write is about 25 minutes and holds the `ultimate` lock; stopping it half-way leaves a half-written disk); nobody is mid-merge; the last gate result is recorded in `docs/wip.md`; every lane has said "packed".

## The copy (the user)

1. Record on the old side, from `tools/readiness`: tip of main, the refs digest. Also build main's tip in the container and record `make size` and the sha256 of `build/breadbin.d64` (they move with main, so record them at the all-stop).
2. Copy the whole directory, `.git` included (the reflog and stashes live there), to the runner's own disk with `rsync -aH` or `tar`, excluding `build/`, `.DS_Store`, `._*`. Never `git clone --local`, `--shared` or `cp -l`: they share inodes. Copy to a fresh path; keep the old tree untouched until the archive is verified, then retire it (rename and make read-only, so no one commits there by mistake).
3. Verify: `tools/readiness` on the runner prints the same refs digest and tip; `git fsck --full` is clean; a sha256 manifest of the working files matches; the archive extracts to scratch and its checksum is recorded.
4. On the runner: `git update-index --refresh` (the index caches inode numbers), `git worktree prune -n` then prune; recreate only the worktrees anyone still needs. Set `gc.auto 0` and `gc.pruneExpire never` until the fleet has been green for a week (old reflog entries, like `8ecb83e`, stay reachable).

## Unpack: step 0 in the new house

Owner: the user for what only they can do, the hygiene agent (C) for the rest. Do these before anyone commits.

1. **Identity.** `git var GIT_AUTHOR_IDENT` and `GIT_COMMITTER_IDENT` resolve to the public facet only; test signing in a throwaway repo, not here. `gh` is the public identity only. Check the repo's `.git/config` for carried-over Mac settings: `core.ignorecase` (set it false on Linux), `core.precomposeunicode`, `gpg.program` or credential helpers pointing at `/opt/homebrew` or the keychain, and `.git/hooks` or `core.hooksPath` with `/Users` paths: `git config -l --show-origin | grep -Ei 'users|homebrew|osxkeychain'`.
2. **Machine.** Time synced (VICE timing is wall-clock); suspend masked; CPU governor `performance`; `loginctl enable-linger` so a dropped ssh does not kill the fleet (run `claude rc` under a systemd user service or tmux, not a bare shell: the lid risk is replaced by a logout risk); disk free for the image store; `ulimit -n` and the process limit for 6 or more VICEs plus Xvfb; `--shm-size` for Xvfb at scale; the registry mirror and apt mirrors reachable.
3. **Containers.** Rootless podman works; `podman info` shows cgroup v2. Build the image from the Containerfile as it stands (pinned: it fails loudly if a version is gone, which is the point). Then: `tools/ci/run.sh size` equals the old side's `make size`, and the d64 sha256 equals the recorded one (expect equal; if the x86_64 build differs, diff before doing anything else). `make test-host` in the container. `tools/ci/run.sh test-smoke` (about 2 minutes). Then one full suite in `BREADBIN_CI_EXCLUSIVE=1` mode, recorded as the new baseline (the 2,511 s figure was arm64 under a laptop's other load: not comparable).
4. **JiffyDOS.** Put the ROMs in place, run a drive test with `BREADBIN_CI_JIFFY` (for instance the one the gate used: `Boot.test_26`) and compare with the recorded host result. This wiring has never run; until it passes, the JiffyDOS gate has no home now that host VICE is retired.
5. **Hardware.** Set the Ultimate address from the environment (never in the repo). Read-only call first (`tools/ultimate.py` status). No write, no imaging, until the facilitator says so. The `ultimate` lock is now on this machine and nowhere else.
6. **Locks.** The lock directory is fresh. `tools/with-lock` slots start at 3: run the sleep-only checks from the commit that introduced it, then raise the cap after the jitter measurement below.
7. **CPU pin (optional, recommended early).** The aim is one CCD for the fleet so a timing run has an L3 of its own. Look first: `lscpu -e=CPU,CORE,SOCKET,CACHE` (which logical CPUs share that CCD's L3 and which are SMT siblings; do not assume the numbering). Try in this order and keep the first that a test shows to work: containers with `--cpuset-cpus=<list>` (rootless needs the cpuset controller delegated to the user manager); containers with `--cgroup-parent=<a slice whose AllowedCPUs is the CCD>`; rootful podman for VICE runs. Prove it: a container that prints `taskset -cp 1` and `/sys/fs/cgroup/cpuset.cpus.effective`. A slot is one physical core, both SMT threads, and about 2 GB (measure the RSS of a VICE container before trusting that). Keep two cores for the agent sessions, git and builds. Protect the fleet's memory with `MemoryLow` and keep desktop work on the other CCD. Jitter baseline: one fixed test (`Boot.test_26_error_messages_from_the_file`) ten times under `-x`, then ten times with 5 others running; the spread sets the slot count. All of this is untested.
8. **The editing path.** If the user edits in an editor on another machine, do it over SFTP or ssh in a worktree of their own on their own branch, never through a network mount of the primary checkout while agents commit.
9. **Stale memory.** The per-project memory has entries written for the laptop (the remote-runner note, the hardware setup with macOS VICE, the landing and lock notes): read each against this house and correct it before anyone relies on it.

## Unpack: the fleet

Principles: the repo is the memory and sessions are disposable; a replacement verifies, it never assumes; light up in waves so the first problems are seen by few.

Waves:

0. The user and the facilitator. The facilitator publishes a roster on `fleet-store` (`fleet/roster.md`: lane, new session name, address) and updates the table in `docs/wip.md`. Every address from the old fleet is dead; messages sent to one fail quietly.
1. Hygiene (C): runs step 0, the idiot check below, and says "house green" with the tip and the numbers (size, d64 sha, smoke, baseline time).
2. Hardware (A): after the read-only Ultimate check.
3. Kernel and the rest, one at a time.

A session is green when it has: (a) identity checked; (b) `git rev-parse main` equal to the recorded tip and the RECORD digest equal; (c) read `CLAUDE.md`, `docs/wip.md`, `docs/process.md`, its own handoff and the luggage manifest; (d) run one real command of its lane (hygiene: `run.sh size`; hardware: the read-only Ultimate call; kernel: `run.sh test-smoke`); (e) sent "green <lane> <tip7>" to the facilitator. The facilitator declares the fleet green when every lane is and the user's list below is done. Until then no commits to main except fixes to the house, nothing pushed (pushes still need the user's go), no hardware write.

First message of a replacement, to its peers: "replacement for <lane>, no memory of the old session, my main tip is <tip7>; resend anything you had in flight to the old one and re-ask any open ask in my handoff." Peers resend; asks that were answered only in the dead session are asked again.

Kickoff text for a new session (the facilitator pastes it): "You are the replacement for <lane>. Read CLAUDE.md, docs/wip.md, docs/process.md, then your handoff on fleet-store and docs/runner-move.md. You have no memory of the old session: check everything against git. Run tools/readiness first and report. Do not push. Say 'green' only when the list in docs/runner-move.md says so."

The user is an honorary member: log in on the runner, `gh` login for the public identity, decide the signing key, place the ROMs and the Ultimate address, answer the first-run permission prompts once (copy the settings allowlist with paths rewritten), start the sessions in wave order, and re-give any approval the old sessions held and the manifests list.

## Recovering from loss

The old tree and the archive stay for at least a week.

1. A file is missing: copy it from the archive; log it in `fleet-store` (`missing.md`, append-only) so the same thing is not found twice.
2. A ref or object is missing, or the RECORD digest differs: stop. Re-copy `.git` from the archive; never rebuild refs by hand.
3. An agent has no context: its transcript is in the luggage, read-only (it cannot be resumed; read it as a document); the handoff and `docs/wip.md` are the first stop.
4. A secret is missing: log in again; nothing re-derives it.
5. A scratch measurement is gone: the numbers worth keeping are in `docs/design/program-size.md` and `docs/wip.md`; re-measure the rest.
6. An interrupted operation (an old `REVERT_HEAD`, `MERGE_HEAD`, a rebase directory, `index.lock`): `tools/readiness` names it. Do not delete the state file; read what was being done first (`git status`, the owner's handoff), then finish or abort it with the owner.

## Postflight idiot check

Hygiene runs it after step 0 and before wave 2, and again at the end of the first working day.

1. `tools/readiness` is READY and its RECORD equals the recorded one.
2. `git fsck --full` is clean; `git worktree list` has only worktrees someone owns; no path in it is a Mac path.
3. `make size` (container) equals the old side; the d64 hash equals; room below `$CF00` is 354 bytes and above the BSS and CODEHI 14 bytes.
4. `tools/with-lock` self-check (three runs, the fourth waits; `-x` waits for all; nested passes through; `ultimate` is single) and `run.sh` takes no slot for `size` and one for `test-smoke`.
5. Two sessions can message each other by the roster's addresses, both ways; a message to a dead address is known to fail quietly.
6. A signed commit on a throwaway branch verifies; `git var GIT_AUTHOR_IDENT` is the public facet; no host name, user name, address or `/Users` path appears in anything staged (`git diff --cached | grep -Ei '/Users|\.local|10\.'`).
7. After one idle night: the sessions are still alive, the clock still agrees, the lock directory is intact (note `/tmp` may be cleared at boot).
8. Backups exist: a periodic `git bundle create --all` to a different disk, and one off the machine on a schedule. One authoritative disk is the risk the move accepts; a bundle is not a second authoritative copy.
9. The docs that name the laptop (`docs/hardware-notes.md` for macOS VICE, `docs/testing.md`, `docs/wip.md`) are marked or fixed; leave the history alone, correct only what a new session would act on.

## Known gaps

- Everything under "Unpack" is unrun.
- JiffyDOS in the container, the CPU pin and the slot count are all unmeasured.
- The Containerfile base image tag floats; pin it by digest on the runner if byte-for-byte reproducibility matters.
- `docs/ci.md` still lists "not done" items (console tests in the container, a result store) that this move makes more pressing.
