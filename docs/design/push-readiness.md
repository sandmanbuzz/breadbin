# Push readiness: local main to origin

Read-only report for the owner. Nothing was pushed, fetched into a branch, or changed in history. Checked on local main `8486912` against `origin/main` `3ff5715` (after a plain `git fetch origin`). Values that are personal or secret are described by kind and location only; they are not copied here.

## 1. How far ahead

- **Commits ahead:** 206 (`origin/main..main`), of which **82 are merges**.
- **Commits behind:** 0. `origin/main` is an ancestor of `main`, so a plain fast-forward push is possible; no force is needed.
- **Branches that the push would send:** only `main` (`git push origin main`). Local branches are not sent unless named. Of the local branches, 27 are **not** merged into `main`, so `main` does not carry them; they stay local unless the owner names them.
- **Origin's refs today:** `origin/main`, `origin/fix/iec-recover`, `origin/hw-bench`, and `origin/HEAD`. The two non-main branches are on origin already (per the 2026-11-01 origin policy, both are merged locally).

## 2. Leak scan (every blob the push would add, 932 objects in the range)

The scan covered all 256 blobs in the range, each commit's author and committer, and every commit message. Each hit is listed by kind and location.

| kind | where (file or commit) | verdict |
|---|---|---|
| personal email address, not the noreply form | `README.md` and `tests/test_system.py` (in the upstream project's text) | **owner decision.** It is the upstream author's public address, from the fork's inherited files. It is not ours and not a secret, but it is not the public identity either. Removing it from the current tree is cheap; removing it from history is a rewrite. |
| hostname or local username | none found | clean |
| absolute home path of the host | none found. The `/home/...` strings in `tests/`, `tools/` and `docs/` are paths inside the C64 test filesystem. | clean |
| internal or private IP address, including the Ultimate's address | none found. Only the loopback address `127.0.0.1` (in `docs/ci.md`, `tools/ci/run.sh`, `tools/vicetest.py`) | clean. The Ultimate address is not in the range. |
| scratch or tmp path of this machine | none found. `/tmp/...` and `claude-<uid>` strings appear only as generic examples in `docs/process.md`, `docs/runner-move.md`, `tools/with-lock`, `tools/readiness` and `tools/workspace.py`, and as C64 paths in `tests/test_system.py` and `docs/hardware-notes.md` | clean |
| volume or mount path | none found. `/mnt/...` strings are C64 paths in `tests/test_system.py`. | clean |
| ROM or JiffyDOS content | none found. No binary blobs in the range; the only mentions are in text (`docs/design/jiffydos-cleanroom.md`, `tools/setup-vice-roms.sh`, two experiment scripts) | clean |
| SSH or GPG key material | none found | clean |
| commit messages naming a model | one hit, a prose word ("modelled") in commit `499b108`. No model identifier. | clean |
| **attribution trailer that the owner's rule rejects** | **29 commits** carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` | **owner decision.** The owner's memory rule says Co-Authored-By is opt-in and no model identifiers go in commits. Fixing it means rewriting these 29 commits, which this report does not do. Options: accept, or rewrite before the first push. |

## 3. Tracked build artifacts or ROMs

`git ls-files` lists **no** object files, listings, maps, disk images, programs, or ROM images (`.o`, `.lbl`, `.map`, `.d64`, `.prg`, `.cx`, `.bin`, `.rom`). Build output lives under `build/`, which is ignored. The largest tracked files are text documents (`docs/hardware-notes.md`, 101 KB; `docs/roadmap.md`; `docs/design/fast-io.md`) and `tools/cc.py`.

## 4. Signatures and identity

- **All 206 commits** in the range are signed with a good signature (`%G?` = `G`), with the key the owner's public identity uses.
- **All 206** have author and committer `sandmanbuzz <344811358+sandmanbuzz@users.noreply.github.com>`.
- **Exceptions: none** on signature or identity. The only exception to the owner's rule is the attribution trailer in section 2.

## 5. Largest new files in the range

41 files are new in the range. The largest:

| file | bytes |
|---|---|
| `tools/cc.py` | 38,847 |
| `docs/runner-move.md` | 28,478 |
| `docs/design/upstream-survey.md` | 18,994 |
| `docs/design/next/cp3-spec.md` | 17,830 |
| `tools/test_cc.py` | 16,232 |
| `tools/test_as.py` | 16,151 |
| `docs/design/feature-priority.md` | 16,149 |
| `docs/design/s14-compiler-spec-draft.md` | 14,779 |

None is a binary or a generated file.

## 6. Proposed push, for the owner to run or approve

Nothing here is pushed. The push is one fast-forward of `main`:

```sh
# 1. the owner decides section 2's two items first (the email in two files; the 29 trailers).
# 2. then, from the primary clone, with the owner's go:
git push origin main
```

- `git push origin main` is a fast-forward (0 behind). Do not add `--force`.
- Do not push the 27 unmerged local branches with it. Push a branch only if the owner names it.
- After the push, `origin/main` equals `main`; re-run section 1 to confirm `0` ahead.

## Decisions for the owner

1. **The 29 `Co-Authored-By: Claude Sonnet 5.5` trailers.** Accept them, or rewrite the 29 commits before the first push. Rewriting changes hashes that other sessions and the roster cite.
2. **The upstream author's personal email** in `README.md` and `tests/test_system.py`. Remove it from the current tree, or leave it as inherited upstream text.
3. **Which of the 27 unmerged local branches**, if any, should be pushed. The default is none.
4. **Whether to push at all today.** The push is safe on the checks above; the decision is timing, and the policy says a push waits for the owner's go.
