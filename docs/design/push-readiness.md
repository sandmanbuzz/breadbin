# Push readiness: local main to origin

Read-only report for the owner. Nothing was pushed, fetched into a branch, or changed in history. Checked on local main against `origin/main` `3ff5715` (after a plain `git fetch origin`), 2026-11-04. Values that are personal or secret are described by kind and location only; they are not copied here.

## 1. How far ahead

- **Commits ahead:** 208 (`origin/main..main`), of which **83 are merges**.
- **Commits behind:** 0. `origin/main` is an ancestor of `main`, so a plain fast-forward push is possible; no force is needed.
- **Branches that the push would send:** only `main` (`git push origin main`). Local branches are not sent unless named. 27 local branches are **not** merged into `main`; they stay local unless the owner names them.
- **Origin's refs today:** `origin/main`, `origin/fix/iec-recover` and `origin/hw-bench` (both already merged into `main`), and `origin/HEAD`.

## 2. Leak scan (every blob the push would add, in the range)

The scan covered all 256 blobs in the unpushed range, each commit's author and committer, and every commit message. Each hit is listed by kind and location.

| kind | where (file or commit) | verdict |
|---|---|---|
| personal email address, not the noreply form | `README.md` and `tests/test_system.py` (in the upstream project's text) | **owner decision.** It is the upstream author's public address, from the fork's inherited files. Removing it from the current tree is a normal commit; removing it from history is a rewrite. |
| hostname or local username | none found | clean |
| absolute home path of the host | none found. The `/home/...` strings in `tests/`, `tools/` and `docs/` are paths inside the C64 test filesystem. | clean |
| internal or private IP address, including the Ultimate's address | none found. Only the loopback address `127.0.0.1` (in `docs/ci.md`, `tools/ci/run.sh`, `tools/vicetest.py`) | clean. The Ultimate address is not in the range. |
| scratch or tmp path of this machine | none found. `/tmp/...` and `claude-<uid>` strings appear only as generic examples in `docs/process.md`, `tools/with-lock`, and as C64 paths in `tests/test_system.py` and `docs/hardware-notes.md` | clean |
| volume or mount path | none found. `/mnt/...` strings are C64 paths in `tests/test_system.py`. | clean |
| ROM or JiffyDOS content | none found. No binary blobs in the range; the only mentions are in text (`docs/design/jiffydos-cleanroom.md`, `tools/setup-vice-roms.sh`, two experiment scripts) | clean |
| SSH or GPG key material | none found | clean |
| commit messages naming a model | one hit, a prose word ("modelled") in commit `499b108`. No model identifier. | clean |
| **attribution trailer that the owner's rule rejects** | **in the unpushed range: 30 commits**, all authored as sandmanbuzz, each with a `Co-Authored-By: Claude Sonnet 5.5` line. **Already on origin: 181 commits** (163 naming Sonnet 5.5, 18 naming Opus 5.5). See section 4. | **owner decision** |

## 3. Tracked build artifacts or ROMs

`git ls-files` lists **no** object files, listings, maps, disk images, programs, or ROM images (`.o`, `.lbl`, `.map`, `.d64`, `.prg`, `.cx`, `.bin`, `.rom`). Build output lives under `build/`, which is ignored. The largest tracked files are text documents (`docs/hardware-notes.md`, 101 KB; `docs/roadmap.md`; `docs/design/fast-io.md`) and `tools/cc.py`.

## 4. Attribution on origin and in the unpushed range

Counts, taken on 2026-11-04 from `git log` on both ranges:

| range | commits | authored as sandmanbuzz | authored as "Claude" | authored as Konstantinos Patronas (upstream) | with a Co-Authored-By trailer |
|---|---|---|---|---|---|
| already on origin (`origin/main`) | 204 | 153 | 33 | 18 | 181 (163 Sonnet 5.5, 18 Opus 5.5) |
| unpushed (`origin/main..main`) | 208 | 208 | 0 | 0 | 30 (all Sonnet 5.5) |

Breakdown of the 181 trailer commits on origin by author: 33 "Claude", 18 upstream (Konstantinos Patronas, the Opus trailers), 130 sandmanbuzz. So the public history already contains the trailers, and 33 public commits are authored as "Claude" rather than sandmanbuzz. Those 33 are not in the unpushed range and rewriting them is an authorship decision, not a cleanup.

## 5. Signatures and identity

- **All 208 unpushed commits** are signed with a good signature (`%G?` = `G`), with the key the owner's public identity uses, and authored and committed as `sandmanbuzz <344811358+sandmanbuzz@users.noreply.github.com>`.
- **Exceptions in the unpushed range: none** on signature or identity. The only exception to the owner's rule is the attribution trailer in section 2.
- **Exceptions on origin:** the 33 "Claude"-authored commits (section 4). Their signatures were not checked in this report.

## 6. Largest new files in the range

41 files are new in the range, not counting the later landings. The largest:

| file | bytes |
|---|---|
| `tools/cc.py` | 38,847 |
| `docs/design/upstream-survey.md` | 18,994 |
| `docs/design/next/cp3-spec.md` | 17,830 |
| `tools/test_cc.py` | 16,232 |
| `tools/test_as.py` | 16,151 |
| `docs/design/feature-priority.md` | 16,149 |
| `docs/design/s14-compiler-spec-draft.md` | 14,779 |

None is a binary or a generated file.

## 7. The options for the trailers and authorship (owner decision)

There are three real options. Each one changes hashes; the cost is what cites them.

**A. Leave it.** Nothing is rewritten and nothing is force-pushed. The 30 unpushed trailers and the 181 public trailers stay, and so do the 33 "Claude"-authored commits. The notes and roster are unaffected.

**B. Rewrite only the 30 unpushed commits**, removing their trailers, then push as a fast-forward. Origin keeps its 181 trailers and its 33 "Claude"-authored commits, so the public history is still mixed. Costs:
- Every unpushed commit after the first trailer commit gets a new hash, which in practice is most of the 208. The push stays a fast-forward because the base, `origin/main`, does not change.
- Hash-keyed records break: `docs/size-ledger.tsv` (4 rows), `docs/program-size-ledger.tsv` (48 rows, one commit), the roster notes, `docs/wip.md`, and the handoff and luggage files on fleet-store that cite hashes. They would need re-keying or a note that maps old to new hashes.
- Signatures are recreated, so the signing key must be available for the rewrite.

**C. Rewrite all of ours and force-push origin.** Our 153 public sandmanbuzz trailer-carrying commits and the 30 unpushed ones lose their trailers, and the 33 "Claude"-authored commits are re-authored as sandmanbuzz. The 18 upstream commits (Konstantinos Patronas) are not ours and should not be rewritten. Costs:
- Force-push is allowed by the origin policy (`docs/process.md`, "Origin": origin is a mirror, and history on it may be rewritten), but the push itself still needs the owner's go.
- Hashes change from the oldest affected commit on origin onward, which is nearly all of origin's history. Every record in section B's list breaks, and so does every external reference to an origin hash (anyone who fetched origin has to reset).
- The re-authoring of the 33 public commits changes who the public history says wrote them. That is a claim about authorship, so it is the owner's decision, not a cleanup.

**Recommendation (for the owner to decide, not applied):** A or B. C changes history that other people may already have fetched, and the 33 re-authored commits change a public claim about authorship. B fixes what this session wrote without touching the public history, but the hash cost is real, so the owner should choose it knowingly.

## 8. Proposed push, for the owner to run or approve

Nothing here is pushed. The push is one fast-forward of `main`:

```sh
# 1. the owner chooses option A, B or C in section 7, and decides the email in section 2.
# 2. for A: from the primary clone, with the owner's go:
git push origin main
# for B the same command runs after the rewrite (not done here); for C it is a force push, which needs its own go.
```

- `git push origin main` is a fast-forward (0 behind). Do not add `--force` unless option C is chosen.
- Do not push the 27 unmerged local branches with it. Push a branch only if the owner names it.
- After the push, `origin/main` equals `main`; re-run section 1 to confirm `0` ahead.

## Decisions for the owner

1. **The attribution trailers and the 33 "Claude"-authored commits**: option A, B or C in section 7.
2. **The upstream author's personal email** in `README.md` and `tests/test_system.py`. Remove it from the current tree, or leave it as inherited upstream text.
3. **Which of the 27 unmerged local branches**, if any, should be pushed. The default is none.
4. **Whether to push at all today.** The push is a clean fast-forward; the decision is timing, and the policy says a push waits for the owner's go.
