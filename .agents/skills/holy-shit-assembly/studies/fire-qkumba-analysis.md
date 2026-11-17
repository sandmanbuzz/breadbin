# Fire Demo qkumba.s: Reverse-Engineering Cutting-Edge Practices

## TITLE
Analyzing `fire_qkumba.s` (64 bytes) from `deater/dos33fsprogs` and extracting engineering practices applicable to the Breadbin codebase.

## PROBLEM
The Apple II fire demo went from 611 bytes to 64 bytes through 37 optimization steps. Each step was a deliberate trade-off between size, correctness, and performance. The question: what engineering practices can we extract and apply to our own assembly code?

## BASELINE
The original `fire.s` (611 bytes) uses:
- Separate `random16` subroutine
- Self-modifying code for address setup
- Full color progression table (16 entries)
- Separate white line setup with absolute addressing
- Monitor ROM calls for graphics setup
- Key press handling with jump to loop

## OBSERVATION: The Optimization History (37 steps)

### Phase 1: Dead Code Removal (611 → 206 bytes)
- 611 → 601: Strip unused code
- 601 → 592: Don't init screen
- 592 → 443: Remove more dead code
- 443 → 206: No need to clear screen
**Pattern:** Before optimizing, eliminate everything that isn't needed. The biggest wins come from removing entire sections, not tweaking individual instructions.

### Phase 2: Algorithm Simplification (206 → 134 bytes)
- 206 → 193: Un-cycle exact the random16 code
- 193 → 189: More optimization of random16 code
- 189 → 161: Move to 8-bit RNG (from 16-bit)
- 161 → 152: Reduce lookup to top half colors
- 152 → 149: Use monitor GR
- 149 → 140: Start using zero-page addressing
- 140 → 139: Rotate instead of mask for low bit
- 139 → 138: `bcs` instead of `jmp`
- 138 → 137: BIT nop trick to get rid of jump
- 137 → 135: Push/pull instead of saving to zero page
- 135 → 134: Replace half of lookup table with math
- 134 → 119: Replace that half with better math
- 119 → 134: Replace other half with math
**Pattern:** The 8-bit RNG was a game-changer. Replacing a 16-bit RNG (which needs more state and more instructions) with an 8-bit LFSR saved ~17 bytes. The lookup table reduction (16 → 8 entries) saved ~15 bytes per half.

### Phase 3: ROM Side-Effect Exploitation (134 → 80 bytes)
- 134 → 132: Replace stack with zp loads
- 132 → 129: Use Y instead of X
- 129 → 125: Optimize low byte generation with branch
- 125 → 113: Make `get_row` a subroutine
- 113 → 112: Regrettable change to low-byte code
- 112 → 109: Replace BIT/OR with ADC
- 109 → 107: Replace self-modifying load/store with Y-indirect
- 107 → 106: Assume bit 8 is as random as bit 0
- 106 → 82: Use VTAB in firmware to setup addresses
- 82 → 81: GR leaves BASL:BASH pointing at line 23 (use Y-indirect)
- 81 → 83: Remove X as counter, use CV instead
- 83 → 83: Flipped x/y loops (too slow, reverted)
- 83 → 81: Call LF to increment CV + VTAB at once
- 81 → 80: Re-arrange random stuff, remove last BIT hack

### Phase 4: The Final 64-Byte Version
- 80 → 64: Use firmware SCROLL for scrolling (adds flicker, saves 16 bytes)
- 64 → 63: SCROLL leaves BAS2L:BAS2H at $7d0 (63-byte version, reverted for correctness)
- 63 → 66: Real hardware check: MIXCLR not set on boot (+3 bytes for correctness)
- 66 → 66: Wasted time on $C050/$C052 access optimization
- 66 → 64: Save/restore SEEDL on stack (the killer optimization)

## INVARIANTS

### The Stack-Based RNG (64-byte version)
```assembly
random8:
    pla               ; Pull seed from stack (1 byte, 1 cycle)
    beq doEor         ; If seed was 0, do EOR
    asl               ; Shift left (1 byte, 2 cycles)
    beq noEor         ; If result was $80, skip EOR
    bcc noEor         ; If no carry, skip EOR
doEor:
    eor #$1d          ; XOR feedback polynomial (2 bytes, 2 cycles)
noEor:
    pha               ; Push back to stack (1 byte, 4 cycles)
```
This is **inlined** at the call site. The seed is kept on the stack, not in zero page. This saves:
- 2 bytes for `lda SEEDL` / `sta SEEDL`
- The SEEDL zero-page entry itself (but it's kept for compatibility)

### The BIT Nop Trick ($2C)
```assembly
    lda <(color_progression),X    ; 3 bytes
    .byte $2c                     ; BIT opcode (1 byte) — nops out next instruction
no_change:
    lda (INL),Y                   ; This becomes the "no change" path
```
The `.byte $2C` emits a `BIT` instruction that takes 2 bytes of space (same as `jmp`/`jsr`) but acts as a no-op. This eliminates the need for a `jmp no_change` (3 bytes) and the label overhead.

### Color Progression Table with Bit-Pattern Encoding
```assembly
color_progression:
    .byte $00   ; 8->0   (1000 -> 0000)
    .byte $bb   ; 9->11  (1001 -> 1011)
    .byte $00   ; 10->0  (1010 -> 0000)
    .byte $aa   ; 11->10 (1011 -> 1010)
    .byte $00   ; 12->0  (1100 -> 0000)
    .byte $99   ; 13->9  (1101 -> 1001)
    .byte $00   ; 14->0  (1110 -> 0000)
    .byte $dd   ; 15->13 (1111 -> 1101)
```
Every even entry (8, 10, 12, 14) maps to 0. This allows using only the low 3 bits of the input as an index (mask with `#$7`), halving the table from 16 to 8 entries. The pattern `00/bb/00/aa/00/99/00/dd` is deliberate: it creates the fire color gradient while exploiting the bit pattern.

### Firmware SCROLL Exploitation
```assembly
scroll_loop:
    jsr SCROLL          ; Scrolls screen up one row (3 bytes)
```
Instead of implementing the scroll loop manually (~16 bytes), they use the ROM SCROLL routine. The trade-off: adds some flicker (ROM scroll is not perfectly synchronized), but saves 16 bytes.

### LF Routine Combination
```assembly
    jsr LF              ; This increments CV and calls VTAB (3 bytes)
    dec CV              ; restore CV (2 bytes)
```
The `LF` routine (at $FC66) increments CV and calls VTAB in one shot. This combines two operations that would otherwise require separate code. The `dec CV` restores CV to its original value for the loop counter.

## TARGET CONTRACT
- CPU: Apple II NMOS 6502 at 1.023 MHz
- ROM: Applesoft or Integer BASIC monitor
- Memory: Zero page at $00-$7F, screen at $0400-$07EF (lo-res)
- Soft switches at $C050-$C056 for graphics mode control
- ROM routines at $F000-$FFFF

## RESULT
The 64-byte version achieves:
- Complete fire animation with scrolling
- 8-bit LFSR PRNG (inlined)
- Color progression table (8 entries, bit-pattern encoded)
- Firmware SCROLL for scrolling
- Stack-based seed storage
- BIT nop trick for branch elimination
- ROM side-effect exploitation (BAS2L:BAS2H after SCROLL)

## VERIFICATION
- Runs on real Apple II hardware (verified by deater)
- Produces the same visual effect as the 611-byte version
- The optimization history is documented in comments
- Multiple variants exist: fire.s (original), fire_tiny.s (105 bytes), fire_firmware.s (83 bytes), fire_qkumba.s (64 bytes)

## TRADE-OFFS
- **Pro:** 64 bytes is astonishing for a complete animation
- **Pro:** The optimization history is a masterclass in systematic reduction
- **Pro:** Each step is documented with a rationale
- **Con:** Flicker from firmware SCROLL (timing-dependent)
- **Con:** The BIT nop trick reduces readability
- **Con:** Stack-based seed is fragile (what if the stack is corrupted?)
- **Con:** Bit-pattern color table is clever but not immediately obvious

## FAILED ALTERNATIVES
1. **16-bit RNG:** Would give better randomness but costs more bytes
2. **Full 16-entry color table:** Would give smoother gradients but costs 8 more bytes
3. **Manual scroll loop:** Would eliminate flicker but costs 16 bytes
4. **Self-modifying code:** Was used in earlier versions but replaced with Y-indirect for clarity
5. **X as counter:** Was used but replaced with CV to save a register

## GENERAL PRINCIPLES (Applicable to Breadbin)

### Principle 1: Eliminate Before Optimizing
The biggest wins (611 → 206) came from removing entire sections, not tweaking individual instructions. Before optimizing a routine, ask: "Do we need this entire section?"

### Principle 2: Exploit ROM Side Effects
The firmware SCROLL and VTAB routines leave registers in useful states. Document these side effects and exploit them. This is what the BAS2L:BAS2H optimization ($7d0 after SCROLL) is about.

### Principle 3: Stack as a Resource
The stack isn't just for return addresses. It can hold temporary state (like the RNG seed) when zero page is at a premium. But document the assumption.

### Principle 4: Bit-Pattern Data Encoding
When data has a regular pattern (like every other entry being 0), encode it to exploit that pattern. The color table uses bit patterns to halve its size.

### Principle 5: Combine Operations
When two operations are always done together (increment CV + call VTAB), find or create a single routine that does both. The `LF` routine is an example.

### Principle 6: Document the Optimization History
The comments in `fire_tiny.s` show every optimization step. This is invaluable for future maintainers to understand why the code looks the way it does.

### Principle 7: Trade-Off Transparency
Each optimization step documents the trade-off: "adds flicker but saves bytes", "regrettable change", "wasted time trying". This helps future decisions.

## REVERSION / FALLBACK
If a trade-off proves too costly (e.g., flicker from SCROLL), revert to the previous version. The optimization history makes this easy.

## SOURCES AND CREDIT
- deater (Vince Weaver) <vince@deater.net>
- qkumba (multiple optimizations credited to him)
- White Flame (8-bit PRNG algorithm)
- Fabien Sanglard (Doom fire algorithm)
- Antoine Vignau (VTAB reminder)
- Source: https://github.com/deater/dos33fsprogs/tree/master/demos/fire

## DECISION
**Adopt principles 1, 2, 6, 7 as project standards.** Principles 3-5 are context-specific (64-byte constraint) but the thinking patterns are transferable.

---

# Application to Breadbin: What We Can Incorporate

## Practice 1: Optimization History as Comments
The `fire_tiny.s` optimization history is a model for our WIP comments. Every time we optimize a routine, we should document:
- What changed
- Why it changed
- What was traded off
- What failed alternatives were tried

This is exactly what we do in `docs/wip.md` but at the routine level.

## Practice 2: ROM Side-Effect Documentation
Our kernel SYS_* routines leave registers in specific states after calls. We should document these side effects in the include file (`breadbin.inc`) so that callers can exploit them.

Example: If `SYS_SPAWN` always returns with X/Y in specific registers, document it and use it.

## Practice 3: Bit-Pattern Data Tables
Our color progression table in `fire_qkumba.s` exploits bit patterns to halve table size. We should look for similar opportunities in our own data tables (opcode tables, syscall tables, etc.).

## Practice 4: Stack as Temporary Storage
When zero page is at a premium, the stack can hold temporary state. But this must be documented and verified (stack depth is bounded).

## Practice 5: Combine Related Operations
When two operations are always done together, create a combined routine. This is what `LF` does (increment CV + VTAB). We should look for similar patterns in our kernel.

## Practice 6: Trade-Off Transparency
Every optimization should document the trade-off. This is what we do in commit messages but should also be in the code comments.
