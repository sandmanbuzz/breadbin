# Pipeline State Machine: sh.s `stage` / `@cl` Loop

## TITLE
The pipeline state machine: how `sh.s` drives multi-stage pipelines with a single loop and one byte of state (`last`).

## PROBLEM
A shell pipeline `a | b | c` must:
- Fork each stage as a separate process (SYS_SPAWN)
- Connect stdout of stage N to stdin of stage N+1 via SYS_PIPE
- Wait for all stages before returning control
- Report background PIDs when `&` is used
- Handle errors in any stage (abort the pipeline)

All of this in ~100 bytes of BSS and a tight loop on a 6502 with no OS scheduler.

## OBSERVATION
The `stage` label (line 904) is the pipeline loop. It does not recurse. It loops back to itself via `jmp stage` (line 1112) for non-final stages, and via `@wait` (line 1105) for the final stage.

The single byte `last` (BSS line 52) encodes the loop invariant:
- `last == 0`: not the final stage — continue to next pipeline iteration
- `last != 0`: this is the final stage — wait for children

The loop invariant: at the top of `stage`, `st_start` points to the first token of the current command, `cmd_end` points past the last token, and `last` tells us whether this is the last command in the pipeline.

The `tmpb` variable (BSS line 64) holds the computed `cmd_end` value at the point where `last` was decided (line 994: `stx tmpb`). This is preserved across the `stage` call so that `@cl` can recompute `st_start = tmpb + 1` for the next iteration.

## HYPOTHESIS
The `last` encoding is not arbitrary. It is chosen because:
1. `bne` (branch if not equal) is the cheapest way to test "is this the final stage?" — it's a single-byte branch instruction that tests for non-zero.
2. `last == 0` means "more work ahead" — the zero flag is naturally set by `lda #0` / `sta last`.
3. The comparison `cpx ntok` at line 993 vs `cpx cmd_end` at line 997 is the pivot: if they're equal, we're at the end of all tokens, so `last` becomes 1; otherwise it stays 0.

The `jmp stage` / `jmp @wait` branch at lines 1112/1105 is the only control-flow divergence point in the pipeline. Everything else is linear: set up I/O, spawn, close, check `last`, loop or wait.

## INVARIANTS
1. `first` (BSS line 51) is always 1 at the start of `stage` and is set to 0 after the first iteration. This distinguishes the first stage (which sets up `prev_in` from the pipeline) from subsequent stages.
2. `npids` counts spawned processes. Every stage increments it. The `@wait` loop uses it as a bound.
3. `bg` is set before `stage` and checked inside `@wait` to decide whether to print the PID.
4. `pr` and `pout` are the pipe file descriptors. `pr` is saved as `prev_in` for the next stage; `pout` is closed after each stage.
5. `pin` is the inherited stdin for the current stage (from previous stage's pipe or `prev_in`).

## TARGET CONTRACT
- CPU: 6502 (NMOS) — `bne`, `bcc`, `bcs`, `jmp`, `jsr` all available
- Machine: C64 / Breadbin kernel with SYS_SPAWN, SYS_WAIT, SYS_PIPE, SYS_CLOSE
- Memory: zero page for pointers (`zp1`, `zp2`), BSS for state
- Stack: used for temporary saves (`pha`/`pla`) in error paths
- Interrupts: assumed disabled or handled by kernel during pipeline setup

## RESULT
The pipeline loop uses:
- ~15 bytes of BSS for pipeline state (`prev_in`, `pin`, `pout`, `pr`, `last`, `bg`, `npids`, `pids[8]`, `first`, `st_start`, `tmpb`)
- A single loop with `jmp stage` for continuation and `jmp @wait` for finalization
- No recursion, no stack frames, no dynamic allocation
- The entire pipeline for `a | b | c` runs in one invocation of `run_cmd`

## VERIFICATION
- Host tests run 672 test cases including pipeline tests
- The `feat/p1-slice1-status-hater-review` branch fixed the `last==0` → continue condition (was incorrectly going to `@wait` for non-final stages)
- 20/20 VICE ShellOperators shard tests pass on the fixed tree

## TRADE-OFFS
- **Pro:** Minimal BSS usage. One loop, one state byte. No recursion depth limits.
- **Pro:** The `last` encoding makes the continuation test a single `bne` — no `cmp #0` needed.
- **Con:** The loop is long (~100 lines) and the continuation logic (`jmp stage` vs `jmp @wait`) is at the very bottom, making it easy to miss when reading top-to-bottom.
- **Con:** `tmpb` is a fragile bridge — it preserves `cmd_end` across the pipeline iteration but its meaning is only clear in context.

## FAILED ALTERNATIVES
1. **Separate `run_stage` function**: Would need to save/restore more state on the stack. The current design avoids stack usage by keeping everything in zero page/BSS.
2. **Recursion**: Would work for short pipelines but risk stack overflow on deep pipelines. The iterative loop is the right choice.
3. **`last` as a pointer**: Could point to a "next stage" token list. But this adds complexity for a pattern that's naturally boolean.

## GENERAL PRINCIPLE
**"Encode loop termination in a boolean that makes the branch test free."**

When a loop has two exit paths (continue vs. finalize), encoding the exit condition as a single byte that can be tested with `bne` / `beq` (no `cmp` needed) is a pattern worth carrying. The zero/non-zero distinction is the cheapest branch predicate on the 6502.

**"Preserve loop state in zero page, not on the stack."**

For tight loops that may execute many times, zero-page state is faster than stack state. The `stage` loop uses `tmpb`, `st_start`, `first` — all zero page — to preserve state across iterations. This is a deliberate choice over stack-based save/restore.

## REVERSION / FALLBACK
If the pipeline loop grows beyond ~150 lines, consider extracting the stage setup (I/O, spawn) into a separate routine and keeping only the loop control in `stage`. The current design works because the loop body is small enough to read in one pass.

## SOURCES AND CREDIT
- `src/bin/sh.s` lines 904-1136: the `stage` loop and `@cl` continuation
- The `last` variable was introduced in commit `f3d4d08` (P0 pipeline regression fix) and refined in `1d48353` (stage_stop removal)
- The `last==0` → continue pattern was the subject of the P0 fix: the original `@cl` had `lda last / bne @wait` which incorrectly skipped continuation for non-final stages

## DECISION
**Retain as experiment** — this pattern is working and well-tested. The `last` encoding + `tmpb` bridge is a compact solution. The main risk is readability: future maintainers need to understand that `last` is not a status code but a "more stages?" flag. A comment at the `last` declaration (line 52) would help.

---

# Coding Standards Derived from Pipeline Analysis

## Standard 1: Boolean State Encoding
When a byte encodes a binary condition used in branch tests, prefer:
- `0` for "false" / "no more" / "not final"
- `1` (or any non-zero) for "true" / "more to come" / "final"

This allows `bne` / `beq` without a preceding `cmp #0`.

## Standard 2: Loop State Preservation
In tight loops that may execute many times:
- Use zero page for state that survives iterations
- Avoid stack save/restore unless the call depth is bounded
- If you must use the stack, document the expected depth

## Standard 3: Continuation Point Documentation
When a loop has multiple exit paths (continue vs. finalize):
- Document the exit condition at the loop entry, not just at the exit
- Use a single byte to encode "continue vs. finalize" and test it with the cheapest branch
- If the loop is >100 lines, add a comment at the bottom explaining the exit logic

## Standard 4: The `tmpb` Bridge Pattern
When a value computed early in a loop must survive to the end:
- Store it in a named zero-page variable at the point of computation
- Use that variable at the exit point, not a recomputed expression
- Document why the variable exists: "bridge: preserves X across loop exit"

## Standard 5: Pipeline State Machine Layout
For pipeline execution:
- Keep the pipeline loop as a single function — no recursion
- Use `first` to distinguish the first stage (sets up `prev_in`) from subsequent stages
- Use `last` to distinguish the final stage (waits) from intermediate stages (continues)
- Track `npids` to know how many children to wait for
- Close pipe FDs in `close_pin` / `close_pout` to avoid descriptor leaks
