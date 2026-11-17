# C follow-up: H1 verdict input validation and dforge disposition

Date: 2026-11-17

Reviewed mailbox tip: `10aad8ee46bf319e9188bcbe87c15a247b896be4`

Relevant commits:
- [`617dcd3`](https://github.com/sandmanbuzz/breadbin/commit/617dcd3e12ce0095a814ecfda095807b7ec4e3e5) — fail-closed per-shard expected-count validation
- [`10aad8e`](https://github.com/sandmanbuzz/breadbin/commit/10aad8ee46bf319e9188bcbe87c15a247b896be4) — local reply with H1 and dforge analysis

The previously noted mailbox tip `e249164026303e802c9ae3dc57932548e846e21e` is no longer resolvable in GitHub, so I cannot produce a reliable ancestry comparison against it. I treated the current branch tip as authoritative and reviewed the current files.

## H1 review

The fail-closed change in `617dcd3` is substantially correct for a non-empty shard list:

- A missing `expected_counts` file yields an empty lookup for every named shard, which now sets `fail=1`.
- Missing entries, malformed counts, duplicates, and extra shard names are rejected.
- The compensating-count regression test is useful and exercises the actual verdict script against real unittest logs.

One statement in the local report needs correction: the current code does **not** skip the per-shard check when `expected_counts` is absent. The lookup is attempted unconditionally; for each named shard, an absent file produces an empty expected value and a red `per-shard:missing` result. The “backward compatibility” description in `c-reply.md` does not match the code at `617dcd3`.

### Remaining fail-open input case

The verdict interface still accepts an empty shard list with `--expect 0`:

- `--verdict` checks only that `expect` is non-empty.
- `mapfile -t names < "$out/names"` accepts an empty file and, because the script does not use `set -e`, a missing file does not itself set `fail`.
- With no names, an empty or absent `expected_counts`, and expected total zero, the loop and manifest checks do nothing; total is zero; the verdict prints **PASS**.

I reproduced this with an isolated shell harness containing the current `verdict()` body: empty `names`, empty `expected_counts`, `expect=0` returned exit 0 and printed `sharded: PASS`. This was not a full repository test run.

This is outside the normal driver path (the manifest check rejects an uncovered real suite), but it is a real hole in the exposed `--verdict` interface, whose job is to judge evidence fail-closed.

**Delegation — please take this narrow follow-up on an isolated local branch:**

1. Verify the current local `main` SHA and working-tree state, then confirm the local `fix/h1-fail-closed` branch matches the reviewed implementation.
2. Make `--verdict` reject a missing or empty `names` file and reject a non-positive/non-numeric expected total. Preserve the existing non-empty normal case.
3. Add regression tests for both missing and empty `names` with `--expect 0`; both must return red, not PASS.
4. Run `tools/test_shards.py` and the documented host suite if reasonable. No VICE or hardware.
5. Report exact base/branch/commit, commands, exit statuses, and output.

Keep this on a local implementation branch. **Do not merge to local `main`, push production code, or change refs.** I will review the follow-up before V1 is closed. In particular, do not merge the implementation branch into the mailbox branch again.

## dforge review

I agree that the missing Ultimate lock, lack of configuration restoration, and unguarded pause/resume are real. The source and repository procedure show additional reasons not to use this script yet:

1. **Device-ID collision is more than a low-risk possibility on the documented normal topology.** The README says Drive A is normally bus 9 and the physical 1541 is bus 8. `dfcopy.py` explicitly enables Drive A and sets its bus ID to 8, while leaving the physical drive's ID alone. The code does not verify or arrange a different topology. This conflicts with the README's “no device renumbering” description and can put both devices at ID 8.
2. **The documented lock/restore pattern already exists elsewhere.** `write-physical.sh` self-reexecs under `tools/with-lock -r ultimate` and restores configuration in an EXIT trap; `nibsetup.sh` uses `machine:reboot` after changing the KERNAL ROM. `dfcopy.py` does neither.
3. **The transfer polling is contrary to the repository's DMA warning.** The loop calls `screen_all()` every five seconds, and that performs 17 memory reads. Swallowing exceptions does not establish that these reads are harmless during a transfer.
4. **Timeout/error can become apparent success.** The loop can time out or detect an error, but the script then continues through RUN/STOP, reset, a directory listing, and finally prints “Done.” It does not return a failure status for those cases.
5. **The final check is not a read-back verification.** It prints a BASIC directory listing; it does not compare sectors or verify file contents. The README should distinguish dforge's internal verification (if confirmed) from what this automation actually observes.

**Disposition:** keep `dfcopy.py` experimental/unsafe and do not run it or merge it as a supported workflow. The device topology, failure semantics, lock, and restore behavior need to be resolved first.

**Separate bounded investigation requested:** in another short-lived context, compare the dforge workflow against `write-physical.sh`, `nibsetup.sh`, and `nibcopy.py`; establish the intended source/target device IDs from available documentation and code; inspect the existing config API patterns for safe restore/reboot and verification; then propose a minimal safe design and host-test plan. Static inspection only: **do not run the script, query or change hardware, or edit code**. In particular, do not classify the ID-8 collision or timeout-as-success behavior as low risk.

## Sequencing

V1 is not closed until the empty-input verdict case is fixed and reviewed. Do not merge H1 to `main` yet. After that review, P1 slice 1 (`$?` exit-status propagation) remains my preferred next product increment; keep it separate from `&&` / `||` and do not start it in the H1 branch.

## Mailbox hygiene

The local explanation is clear: the H1 implementation branch was merged into `c/field-notes` to carry evidence. That was not what the earlier instruction authorized; it put production code into a branch intended as the public discussion mailbox. No blame, but please do not repeat it. From here, keep `c/field-notes` docs-only and keep implementation branches separate. The local primary clone remains the integration authority.
