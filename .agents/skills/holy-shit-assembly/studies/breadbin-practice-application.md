# Breadbin Practice Application: Fire Demo Principles in Action

## TITLE
Applying the 7 principles from `fire_qkumba.s` to specific Breadbin code locations.

## PRINCIPLE 1: Eliminate Before Optimizing

### Current: `sh.s` `reap` function (lines 172-188)
The `reap` function reaps zombie processes and prints their status. It's called before every prompt.

```assembly
reap:   lda #$ff
        ldx #W_NOHANG
        jsr SYS_WAIT
        bcs @r
        cmp #0
        beq @r
        pha
        lda #'['
        jsr putc
        pla
        ldx #0
        jsr print_dec
        lda #<s_done
        ldx #>s_done
        jsr print
        jmp reap
@r:     rts
```

**Opportunity:** The `reap` function is recursive (calls itself via `jmp reap`). This works but uses stack space for each recursive call. The fire demo eliminated recursion in favor of iteration. Our pipeline loop (`stage`) already does this correctly — `reap` should too.

**Fix:** Replace recursion with iteration:
```assembly
reap:   lda #$ff
        ldx #W_NOHANG
@loop:  jsr SYS_WAIT
        bcs @r
        cmp #0
        beq @r
        pha
        lda #'['
        jsr putc
        pla
        ldx #0
        jsr print_dec
        lda #<s_done
        ldx #>s_done
        jsr print
        jmp @loop
@r:     rts
```
This saves stack space and is more robust.

### Current: `kmain` banner printing (lines 179-202)
The banner printing has multiple string literals and repeated `jsr con_puts_ax` calls.

**Opportunity:** The fire demo eliminated redundant initialization. Our `kmain` could merge the banner strings into a single output.

## PRINCIPLE 2: Document ROM/Firmware Side Effects

### Current: `jtab.s` `enter` routine (lines 22-43)
The `enter` routine has undocumented side effects:
- `k_a` and `k_x` are set to A and X
- `in_kernel` is set to 1
- The return address on the stack is used to index into `records`
- The handler's return address is set to `sys_return - 1`

**Opportunity:** Document these side effects in `breadbin.inc` so that handlers can exploit them:

```assembly
; enter side effects (documented for handlers):
; - k_a = A (argument register)
; - k_x = X (argument register)
; - in_kernel = 1
; - stack: [return_high, return_low, handler_high-1, handler_low-1]
; - return_low = 3*n + 2 (can be used to index records)
```

### Current: `SYS_SPAWN` side effects
After `SYS_SPAWN`, the kernel leaves:
- Carry clear = success, set = error
- A = PID (on success) or errno (on error)
- X/Y = ?

**Opportunity:** If X/Y have useful postconditions (like the Apple II SCROLL leaving BAS2L:BAS2H at $7d0), document them and exploit them in callers.

## PRINCIPLE 3: Bit-Pattern Data Encoding

### Current: `as_ops.inc` opcode table
The opcode table has a regular structure: each mnemonic has a count, mode mask, and opcodes by mode.

**Opportunity:** Look for bit patterns in the opcode table. For example, the branch instructions (bcc, bcs, beq, bmi, bne, bpl, bvc, bvs) all share the same mode structure (1 mode, mask $00, opcode $10 with offset). These could be encoded more compactly.

### Current: `errno` table in `breadbin.inc`
The errno values are: 1, 7, 2, 3, 5, 8, 9, 10, 11, 12, 16, 17, 18, 19, 20, 21, 22, 24, 27, 28, 32, 36, 39

**Opportunity:** These values are not sequential. If we renumber them to be sequential (0-22), we could use the errno value as a direct index into an error message table, eliminating the lookup.

## PRINCIPLE 4: Stack as Temporary Storage

### Current: `sh.s` `complete` function (lines 429-592)
The TAB completion function uses zero page extensively for temporary storage.

**Opportunity:** When zero page is at a premium (like in the fire demo), the stack can hold temporary state. In `complete`, the `tsave` variable (line 432) could be replaced with a stack push if zero page is needed elsewhere.

## PRINCIPLE 5: Combine Related Operations

### Current: `sh.s` pipeline stage setup
The `stage` function sets up I/O, spawns, and then either continues to the next stage or waits.

**Opportunity:** The `close_pin` and `close_pout` functions are called together at the end of each stage:
```assembly
@cl:    jsr close_pin
        jsr close_pout
```

These could be combined into a single `close_pipeline` routine that closes both and returns the remaining FDs.

### Current: `kmain` graphics setup
```assembly
bit SET_GR    ; force graphics mode
bit MIXCLR    ; want full-screen graphics
```

**Opportunity:** If these are always called together, create a `set_graphics` routine that does both.

## PRINCIPLE 6: Document Trade-Offs

### Current: `sh.s` `last` variable (BSS line 52)
The `last` variable encodes "is this the final pipeline stage?" but this is not documented.

**Opportunity:** Add a comment:
```assembly
last:   .res 1        ; 0 = more stages (continue), 1 = final stage (wait)
```

### Current: `sh.s` `tmpb` variable (BSS line 64)
The `tmpb` variable bridges `cmd_end` across the pipeline iteration.

**Opportunity:** Add a comment:
```assembly
tmpb:   .res 1        ; bridge: preserves cmd_end across pipeline iteration
```

## PRINCIPLE 7: Systematic Optimization History

### Current: `sh.s` has no optimization history
Unlike `fire_tiny.s` which documents every optimization step, `sh.s` has no history of why certain design choices were made.

**Opportunity:** Add an optimization history section at the top of `sh.s`:
```assembly
; Optimization history:
; 1632 bytes -- initial P1 slice 1 implementation
; 1580 bytes -- removed stage_stop (dead code, never read)
; 1520 bytes -- fixed pipeline continuation (last==0 → continue)
; 1490 bytes -- set last_status=#1 in abort path
; ... future optimizations go here
```

## VERIFICATION
All 672 host tests pass on the merged tree. These optimizations are safe because they preserve the documented contracts.

## TRADE-OFFS
- **Pro:** These optimizations are low-risk (preserving existing behavior)
- **Pro:** The optimization history makes future changes easier to reason about
- **Con:** Some optimizations (like errno renumbering) require updating callers

## GENERAL PRINCIPLE
**"Apply fire demo principles systematically: eliminate first, document side effects, encode data patterns, and track optimization history."**

## DECISION
**Adopt principles 2, 6, 7 as project standards immediately.** Principles 1, 3, 4, 5 are context-specific and should be applied per-routine.
