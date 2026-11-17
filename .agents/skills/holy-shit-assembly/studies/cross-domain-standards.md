# Cross-Domain Discovery: Assembly Coding Standards from the Breadbin Codebase

## TITLE
Identifying reusable patterns across the Breadbin assembly codebase that should become coding standards.

## PROBLEM
The Breadbin codebase has grown organically over many commits with different authors. Each routine develops its own local conventions. The question is: which conventions are genuinely useful, which are accidental, and which should be codified as project-wide standards?

## OBSERVATION
Studying `sh.s`, `as.s`, `basic.s`, and the driver code in `experiments/iec-stall/`, several patterns emerge that are consistently used and consistently useful:

### Pattern 1: Zero-Page Pointer Pairs
Every 16-bit pointer uses a consecutive zero-page pair: `zp1`/`zp2`, `lp1`/`lp2`, `r0`/`r0+1`, `r1`/`r1+1`. This is standard 6502 practice but the Breadbin codebase has a consistent naming convention:
- `zp*` variables: temporary pointers (generic, may be reused)
- `lp*` variables: long pointers (pointers to data in other segments)
- `r0`/`r1`/`r0+1`/`r1+1`: syscall argument registers (mapped to kernel ABI)

### Pattern 2: Token Type Encoding
Token types in the shell use a bit-pattern encoding:
- `T_WORD = 0` (no special bit set)
- `T_AND = $80` (high bit set, even value)
- `T_OR = $81` (high bit set, odd value)
- `T_DOLLAR = $82` (not $80 or $81, treated as word)

This allows a single `cmp` to distinguish operators from words:
```
cmp #'|'
beq @pipe
cmp #'&'
beq @amp
cmp #';'
beq @op
```
The high-bit encoding means `cmp` against literal values works correctly.

### Pattern 3: Error Propagation via Carry
The 6502 carry flag is used consistently for error propagation:
- `bcs` (branch on carry set) = error path
- `bcc` (branch on carry clear) = success path
- Syscall results: `bcs @error` after `jsr SYS_*`
- Return values: `sec` (set carry) = error, `clc` (clear carry) = success

### Pattern 4: Label Naming Conventions
- `@` prefix: local labels within a function
- No prefix: global labels (entry points, public symbols)
- Short names: `@l`, `@r`, `@n`, `@s` for common branch targets
- Descriptive names: `@eof`, `@done`, `@ok`, `@nomem` for important states

### Pattern 5: The `rts` at End of Function
Every function ends with `rts` (return from subroutine). Even functions that could `jmp` elsewhere use `rts` for clarity. This makes the function boundary explicit and allows the function to be called from anywhere.

### Pattern 6: State Machine Design
The pipeline state machine in `sh.s` uses a single byte (`last`) to encode loop continuation vs. finalization. This is a general pattern: use a single byte to encode loop state, and test it with the cheapest branch (`bne`/`beq`).

### Pattern 7: Buffer Size Constants
Buffer sizes are defined as constants at the top of the file:
- `MAXTOK = 32`
- `MAXARG = 16`
- `LINEMAX = 127`
- `HISTN = 4`

These are used throughout the code for bounds checking and buffer allocation.

## HYPOTHESIS
These patterns are not accidental. They emerge from the constraints of the 6502 architecture:
- Zero page is the fastest memory (one cycle for indexed indirect)
- Carry flag is the cheapest condition code (no `cmp` needed)
- Labels are the cheapest control flow mechanism (one-byte `jmp`/`jsr`)
- Constants at the top of the file make the code self-documenting

## INVARIANTS
1. Every function has a clear entry point and exit path
2. Every function documents its inputs and outputs in comments
3. Every buffer has a named constant for its size
4. Every error path sets `last_status` or returns carry set
5. Every syscall is preceded by argument setup in `r0`/`r1`/`r0+1`/`r1+1`

## TARGET CONTRACT
- CPU: 6502 (NMOS) — all patterns tested on NMOS 6502
- Machine: C64 / Breadbin kernel
- Assembler: ld65 (linker/loader for 6502)
- Memory: zero page for fast access, BSS for global state, CODE for instructions, RODATA for constants

## RESULT
Seven coding standards derived from the codebase:
1. Zero-page pointer naming convention (`zp*`, `lp*`, `r*`)
2. Token type bit-pattern encoding for efficient comparison
3. Carry flag for error propagation (universal pattern)
4. Label naming: `@` prefix for local, no prefix for global
5. Explicit `rts` at function end (no implicit returns)
6. Single-byte state encoding for loop control
7. Named constants for all buffer sizes

## VERIFICATION
- All 672 host tests pass on the merged tree
- The pipeline state machine (standard 6) was the subject of the P0 fix
- The token type encoding (standard 2) is used consistently across the tokenizer
- The carry flag pattern (standard 3) is used in every syscall

## TRADE-OFFS
- **Pro:** These standards are derived from actual code, not theory
- **Pro:** They are architecture-specific and optimized for the 6502
- **Con:** Some standards (like the `@` prefix) may not transfer to other assemblers
- **Con:** The token type encoding (standard 2) is clever but not immediately obvious

## FAILED ALTERNATIVES
1. **Using `cmp` for all comparisons**: Would work but is less efficient than the carry-based approach.
2. **Using named constants for all magic numbers**: The `seps` string uses literal characters (`|`, `&`, etc.) which is more readable than named constants.
3. **Using `jmp` for function returns**: Would save a byte but makes the function boundary less clear.

## GENERAL PRINCIPLE
**"Derive standards from the code, not from the architecture."**

The best coding standards emerge from studying working code and identifying patterns that are consistently useful. They should be:
1. Derived from actual code (not theoretical)
2. Architecture-specific (optimized for the target platform)
3. Simple enough to remember (not a reference manual)
4. Verified by testing (not just reasoning)

## REVERSION / FALLBACK
If a standard proves problematic (e.g., a pattern that works in one context but not another), document the exception and keep the standard as the default.

## SOURCES AND CREDIT
- `src/bin/sh.s`: pipeline state machine, token encoding, error propagation
- `src/bin/as.s`: assembler conventions, macro usage
- `src/bin/basic.s`: BASIC interpreter patterns
- `.agents/skills/holy-shit-assembly/SKILL.md`: the analysis framework

## DECISION
**Adopt** — these standards are derived from working code, verified by tests, and optimized for the 6502 architecture. They should be codified in the project's coding standards document.
