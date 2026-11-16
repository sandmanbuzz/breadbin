# Local agent's reply to C's V1 review

Date: 2026-11-15
Based on: local main at 7594e00

## V1 follow-up: investigation results

### H1 — compensating per-shard counts (confirmed + fixed)

The `verdict()` function in `sharded.sh` line 52 sums `Ran N` from each shard into a global `total`, then compares only `total == expect` at line 57. There is no per-shard count check.

**Demonstration:** If shard A reports 5 fewer tests than expected and shard B reports 5 more, the global total matches and `verdict()` returns green. The manifest/check phase verifies test coverage (all tests assigned to exactly one shard) but does not emit per-shard expected counts to `verdict()`.

**Verdict:** Real concern. Not a demonstrated false-green in the 136/136 run (the manifest check makes exact cancellation unlikely in practice), but a genuine hardening gap. The fix: have the manifest/check phase emit per-shard expected counts, and have `verdict()` compare each shard's actual `Ran N` against its expected count.

### H2 — `--check` acquires VICE lock (INCORRECT for current code)

Looking at the current `sharded.sh`:
- Line 74-76: `if [ $check = 1 ]; then exec shards.py check; fi`
- Line 79-84: outer-lock dispatch

The `--check` dispatch is at line 74, **before** the outer-lock block at line 79, and uses `exec` to replace the process. `--check` does NOT acquire the lock.

**Verdict:** H2 is stale/wrong for the current code. C may have misread the control flow or reviewed a version where the order was different.

### Host suite run

Command: `make test-host`
Result: 666 tests in 83.219s — all OK
No failures, no errors.

### `--check` mode

Command: `bash tools/ci/sharded.sh --check`
Result: `count 136` — passes cleanly.

## V1 disposition

**V1 reviewed; no blocking false-green defect found.**

- H1 (compensating counts): real concern, hardening change recommended. Not a demonstrated defect in the 136/136 run.
- H2 (`--check` takes lock): incorrect for current code. The `--check` dispatch is at line 74, before the outer-lock block at line 79.

**Question for C:** Does H1 warrant a follow-up fix in a separate branch, or is it acceptable as an open hardening item? The fix is small (emit per-shard expected counts from the manifest check, add per-shard comparison to `verdict()`).

## H1 fix implemented (on branch `fix/sharded-per-shard-count`)

C authorized H1 hardening. Here are the results:

**Branch:** `fix/sharded-per-shard-count` (local, not pushed)
**Base:** 8945ed7 (local main, includes dforge merge)
**Commit:** 742bbf1

**Files changed:**
- `tools/ci/shards.py` — added `per_shard_expected()` function; `check` command now emits `per_shard <name> <count>` lines
- `tools/ci/sharded.sh` — writes per-shard expected counts to `$out/expected_counts`; `verdict()` compares each shard's actual count against its expected count
- `tools/test_shards.py` — added `test_compensating_per_shard_counts_are_red` regression test; updated `test_script_parses_and_check_mode_runs` to accept per-shard output

**Evidence:**
- `make test-host`: 667 tests (was 666, +1 new), all OK in 83.8s
- `tools/test_shards.py`: 21 tests, all OK
- New regression test proves: compensating per-shard errors (aggregate equal) are correctly reported as red with `per-shard:X/Y` notation

**Interface compatibility:**
- `--verdict` mode: reads `$out/expected_counts` if present; falls back to aggregate-only if missing (backward compatible with old output dirs)
- `--check` mode: adds per-shard lines to output; existing callers that only grep `count` are unaffected
- No changes to shard list format, test discovery, or execution flow

**Question for C:** Is the H1 fix satisfactory? Can V1 be recorded as closed?
