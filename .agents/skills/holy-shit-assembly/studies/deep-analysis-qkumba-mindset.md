# The Deep Analysis: What Makes qkumba's Code "Genius Level"

## TITLE
Not "what optimizations" but "what kind of thinking." Not "how to be -Os" but "how to violate convention at the foundation."

## PROBLEM
We write high-quality assembly that follows convention. qkumba writes assembly that *creates* convention. The gap isn't skill — it's a different model of the machine.

## BASELINE: Conventional 6502 Thinking
Every assembly programmer learns these rules:
1. Zero page = fast variables
2. Stack = return addresses + saved registers
3. ROM = call subroutines, don't care about side effects
4. Registers = temporary values, save before use
5. Data = data, code = code
6. Memory = storage
7. Optimization = "make this smaller/faster within the rules"

## OBSERVATION: qkumba's Rules Are Different

### Rule 1: The Stack is a Register
```assembly
random8:
    pla               ; Pull seed from stack (NOT from zero page)
    beq doEor
    asl
    beq noEor
    bcc noEor
doEor:
    eor #$1d
noEor:
    pha               ; Push back to stack (NOT to zero page)
```

**Conventional:** The RNG seed lives in `SEEDL` ($4E), a zero-page variable. You read it, compute, write it back.

**qkumba's thinking:** The stack top IS a register. It's mutable, it's fast (one instruction to access), and it's bounded (the RNG is inlined, so stack depth is controlled). The stack isn't a mechanism — it's a resource.

**Why it works:** The RNG is inlined at the call site. The stack push/pop is part of the algorithm, not a side effect. The seed is always restored before the next iteration. Stack depth is bounded by the algorithm structure.

**Why it's genius:** It violates the fundamental assumption that "the stack is for return addresses." qkumba treats the stack as a general-purpose storage area with push/pop semantics. This is the same insight that makes register allocators work: the stack is just another register file.

### Rule 2: ROM Side Effects Are a Protocol
```assembly
; After SCROLL: Y = 40, BAS2L:BAS2H = $7d0
; These are NOT documented. qkumba DISCOVERED them.
w_loop:
    lda #$ff
w_loop:
    sta (BAS2L),Y     ; Use BAS2L:BAS2H as a pointer — no calculation needed
    dey
    bpl w_loop
```

**Conventional:** Call a ROM routine. It does its thing. Return. Don't care what registers are left.

**qkumba's thinking:** The ROM is a state machine. Every call leaves the machine in a specific state. That state is a resource. The BAS2L:BAS2H pointer after SCROLL is "free" — no calculation needed to draw the white line.

**Why it works:** The Apple II ROM is deterministic. SCROLL always leaves BAS2L:BAS2H at $7d0. This is a hardware fact, not a coincidence.

**Why it's genius:** It treats the ROM not as a black box but as a protocol with observable state. This is the same insight that makes system programming work: every function call changes the machine state, and that state is part of the interface.

### Rule 3: Data Encodes Algorithm
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

**Conventional:** A lookup table maps input to output. 16 entries for 16 colors.

**qkumba's thinking:** The data has a bit pattern: every even entry (bit 7 = 1) maps to the same value as the corresponding odd entry (bit 7 = 0). So the low 3 bits of the input are sufficient as an index. The table is halved from 16 to 8 entries, and the algorithm uses `and #$7` to exploit this.

**Why it works:** The color transformation has a natural bit pattern. The high bit (bit 7) doesn't affect the output. This is a property of the fire algorithm, not an arbitrary choice.

**Why it's genius:** The data structure encodes the algorithm. The table isn't just a mapping — it's a compressed representation. The algorithm `and #$7` is both a mask AND an index extractor. One instruction does two things.

### Rule 4: Code/Data Duality
```assembly
    lda <(color_progression),X    ; 3 bytes
    .byte $2c                     ; BIT opcode (1 byte) — acts as nop
no_change:
    lda (INL),Y                   ; Fall through to the "no change" path
```

**Conventional:** `.byte` emits data. `BIT` is an instruction. They're different things.

**qkumba's thinking:** A byte can be both data and code. `.byte $2C` emits a BIT instruction that acts as a no-op in this context, saving a byte compared to `jmp no_change` (3 bytes).

**Why it works:** BIT reads memory but doesn't modify it. In this context, we don't need the read — we just need the byte to take up space and act as a fall-through point.

**Why it's genius:** It blurs the boundary between code and data. The byte `$2C` is both a data value (the BIT opcode) and a code instruction (BIT). This is the same insight that makes self-modifying code work: code is just data at the right time.

### Rule 5: Operation Fusion
```assembly
; Before: separate CV increment + VTAB call
; After:  jsr LF  (which does both)
    jsr LF              ; Increment CV AND call VTAB in one shot
    dec CV              ; Restore CV for the loop counter
```

**Conventional:** Two operations → two calls. Each has its own entry point, its own overhead.

**qkumba's thinking:** When two operations are always done together, they should be a single operation. LF is a ROM routine that does both. The `dec CV` restores the loop counter.

**Why it works:** The Apple II ROM has a routine (LF at $FC66) that increments CV and calls VTAB. qkumba discovered this and used it.

**Why it's genius:** It's not just "use a subroutine" — it's "find the subroutine that does exactly what you need, even if it wasn't designed for your use case." This is the same insight that makes library design powerful: the best APIs are the ones that do exactly what you need.

## INVARIANTS

### The Machine as a State Machine
Every instruction changes the machine state. Every ROM call changes the machine state. The state includes:
- Registers (A, X, Y, S, P)
- Memory (zero page, RAM, ROM)
- I/O state (soft switches, device registers)
- Stack state (top of stack, stack pointer)

qkumba's genius is treating ALL of these as resources, not just the registers.

### The Stack is Not Sacred
The stack is not for return addresses. It's for storage. Return addresses are just a side effect of `jsr`. The stack top is a register with push/pop semantics.

### ROM Is Not a Black Box
ROM routines are not just subroutines. They are state machines with observable side effects. Every call leaves the machine in a specific state. That state is part of the interface.

### Data Encodes Computation
Data structures are not just storage. They can encode algorithms. A table can be a compressed representation of a function. A bit pattern can be an index extractor.

### Code and Data Are the Same Thing
At the machine level, code is data and data is code. The difference is only in how you interpret the bytes. Exploit this duality.

## TARGET CONTRACT
- CPU: Apple II NMOS 6502 at 1.023 MHz
- Memory: 4KB RAM, 16KB ROM
- Zero page: $00-$7F (128 bytes)
- Stack: $0100-$01FF (256 bytes)
- ROM: $F000-$FFFF (4KB)
- Constraint: 64 bytes for a complete fire animation

## RESULT
The 64-byte version violates every convention:
1. **Stack as register:** The RNG seed lives on the stack, not in zero page
2. **ROM state as resource:** BAS2L:BAS2H after SCROLL is used as a pointer
3. **Data as algorithm:** The color table encodes the color transformation
4. **Code/data duality:** The BIT $2C byte is both opcode and data
5. **Operation fusion:** LF combines CV increment + VTAB

## VERIFICATION
- Runs on real Apple II hardware
- Produces the same visual effect as the 611-byte version
- The optimization history documents every step
- Multiple variants exist, each exploring a different aspect

## TRADE-OFFS
- **Pro:** 64 bytes is astonishing
- **Pro:** Each violation of convention is justified by a clear trade-off
- **Con:** The code is harder to read (stack as register is unconventional)
- **Con:** Some exploits are hardware-specific (BAS2L:BAS2H after SCROLL)
- **Con:** The BIT $2C trick is obscure (future maintainers won't understand)

## FAILED ALTERNATIVES
1. **Keep SEEDL in zero page:** More readable, costs 2 bytes more
2. **Use full 16-entry color table:** Smoother gradients, costs 8 more bytes
3. **Manual scroll loop:** No flicker, costs 16 more bytes
4. **Self-modifying code:** Was used in earlier versions, replaced with Y-indirect for clarity
5. **Separate CV increment + VTAB:** More flexible, costs more bytes

## GENERAL PRINCIPLE
**"The machine is a state machine. Every byte of state is a resource. Conventions are just habits — break them when the math works."**

The four foundational violations:
1. **Stack is mutable storage**, not just return addresses
2. **ROM side effects are a protocol**, not noise
3. **Data encodes algorithm**, not just values
4. **Code and data are dual**, not separate

## REVERSION / FALLBACK
If a violation proves too fragile (e.g., BAS2L:BAS2H after SCROLL changes on a different machine), revert to the conventional approach. Document the assumption.

## SOURCES AND CREDIT
- deater (Vince Weaver) <vince@deater.net>
- qkumba (multiple optimizations credited)
- White Flame (8-bit PRNG algorithm)
- Fabien Sanglard (Doom fire algorithm)
- Source: https://github.com/deater/dos33fsprogs/tree/master/demos/fire

## DECISION
**Adopt all four foundational violations as mental models.** Don't just apply the techniques — adopt the mindset.

---

# Mind-Blowing Techniques: Applied to Breadbin

## Technique 1: Stack as Mutable Storage

### Fire Demo Example
The RNG seed lives on the stack. `pla`/`pha` replaces `lda SEEDL`/`sta SEEDL`.

### Breadbin Application: Syscall Handler Table

The current syscall table at $CF00 uses the return address on the stack as an index:
```assembly
; jtab.s: enter routine
enter:
    pla         ; low byte of return address = 3*n + 2
    tax
    pla         ; high byte
    ; X = 3*n + 2, used to index into records
```

**Conventional:** The records table at $CF00+48 stores handler addresses. Each entry is 3 bytes.

**qkumba-style:** What if the handler address itself was on the stack, not in a table? When `enter` is called, the return address points to the jsr instruction. The low byte of the return address IS the syscall number (3*n + 2). We could use this directly to compute the handler address without a table lookup.

**The mind-blowing insight:** The return address on the stack is already the index. We don't need the records table at all. We can compute the handler address from the return address:

```
handler = SYS_BASE + (return_low - 2) / 3 * 3 + handler_offset
```

But wait, the current design already does this cleverly. The records table maps the return address to the handler. What if we made the records table implicit?

**Truly mind-blowing:** What if the syscall table entries were structured so that the return address directly indexes into the handler addresses? Like:

```assembly
; Instead of:
.repeat NSYS
    jsr enter
.endrep

; We could use:
.repeat NSYS
    jsr enter
    .word handler_addr   ; Inline the handler address after each jsr
.endrep
```

Then `enter` could read the handler address from the return address location itself, eliminating the need for a separate records table. This is the code/data duality principle: the bytes after the jsr serve dual purposes (data for the linker, code for the handler lookup).

### Breadbin Application: Pipeline State

In `sh.s`, the pipeline state machine uses `last` to encode "more stages?" and `tmpb` to bridge `cmd_end` across iterations.

**qkumba-style:** What if `last` lived on the stack instead of in zero page? The pipeline loop is bounded (max 8 stages), so stack depth is controlled. Using the stack for `last` would free a byte of zero page.

**The violation:** Zero page is at a premium in sh.s (80+ bytes used). Using the stack for pipeline state would be a resource optimization that violates the convention "pipeline state belongs in zero page."

## Technique 2: ROM Side Effects as Protocol

### Fire Demo Example
BAS2L:BAS2H after SCROLL = $7d0. Y after SCROLL = 40. These are undocumented side effects that qkumba discovered and exploited.

### Breadbin Application: Kernel Side Effects

Our kernel SYS_* routines have undocumented side effects:
- `SYS_SPAWN`: What registers are left after a successful spawn?
- `SYS_WAIT`: What registers are left after a wait?
- `SYS_PIPE`: What registers are left after a pipe creation?

**qkumba-style:** Document these side effects and exploit them. For example, if `SYS_SPAWN` always leaves X/Y pointing at the new process's PCB, the shell could use this directly instead of looking up the PID.

**The mind-blowing insight:** The kernel's internal state (process table, file descriptor table) could be exposed through register side effects, not just return values. This is like the Apple II ROM leaving BAS2L:BAS2H at $7d0 — the kernel's state becomes a resource.

### Breadbin Application: Scheduler State

The scheduler leaves `cur` set to the current process slot. Handlers could read `cur` directly instead of being passed it.

**The violation:** Convention says "pass state explicitly." qkumba says "read state from the machine." The scheduler's `cur` variable is a side effect that handlers can exploit.

## Technique 3: Data Encodes Algorithm

### Fire Demo Example
The color progression table exploits bit patterns (every even entry maps to the same value as the corresponding odd entry). The algorithm uses `and #$7` to extract a 3-bit index, halving the table from 16 to 8 entries.

### Breadbin Application: errno Table

The errno values in `breadbin.inc` have patterns:
- Sequential groups: 2,3; 8,9,10,11,12; 16-22; 24,27,28,32,36,39
- Gaps at: 4,6,7,13,14,15,23,25,26,29,30,31,33,34,35

**qkumba-style:** What if we compressed the errno-to-message mapping by exploiting these patterns? Instead of a 40-entry table, use a sparse encoding where sequential groups are compressed.

**The violation:** Convention says "errno values are fixed by POSIX." But the MESSAGE TABLE doesn't need to be indexed by errno. We could use a compressed encoding where the table is indexed by a derived value, not the errno itself.

### Breadbin Application: Opcode Table

The opcode table in `as_ops.inc` has a regular structure: count, mode mask, opcodes by mode.

**qkumba-style:** The mode mask ($dc, $da, $00, etc.) encodes which modes are legal for each mnemonic. What if we encoded this differently? For example, use a bitmap where each bit represents a mode, and the count is derived from the number of set bits.

**The violation:** Convention says "store the count explicitly." qkumba says "derive the count from the data." The table becomes smaller because the count is computed, not stored.

## Technique 4: Code/Data Duality

### Fire Demo Example
The BIT $2C byte acts as both an opcode (BIT) and data (a byte that takes up space). It's a nop in this context because BIT reads memory without modifying it, and we don't care about the read.

### Breadbin Application: Syscall Table Entry Encoding

The current syscall table uses `jsr enter` for each entry. The return address is used as an index.

**qkumba-style:** What if the entry encoding served dual purposes? Instead of:
```assembly
jsr enter    ; 3 bytes: JSR $CFXX
```

We could use:
```assembly
jsr enter
.byte n      ; The syscall number, used by enter as an index
```

Then `enter` would read the byte after the jsr (from the return address) to get the syscall number directly, eliminating the need for the records table.

**The violation:** Convention says "the byte after jsr is part of the next instruction." qkumba says "the byte after jsr is data that happens to be adjacent to code." This is the same insight that makes self-modifying code work.

### Breadbin Application: Shell Token Types

In `sh.s`, token types use bit patterns:
- `T_WORD = 0`
- `T_AND = $80`
- `T_OR = $81`
- `T_DOLLAR = $82`

**Current convention:** Token types are encoded with the high bit set for operators.

**qkumba-style:** What if we encoded the token type directly in the character? Instead of a separate token type table, use the character value itself to determine the token type. For example, `|` could have its high bit set to indicate it's an operator, and the low 7 bits could be the operator code.

**The violation:** Convention says "tokens have separate type and value." qkumba says "the value encodes the type." This is the data-encodes-algorithm principle applied to tokenization.

## Technique 5: Operation Fusion

### Fire Demo Example
LF combines CV increment + VTAB into a single ROM call. Two operations that are always done together → one operation.

### Breadbin Application: close_pin + close_pout

In `sh.s`, these are always called together:
```assembly
@cl:    jsr close_pin
        jsr close_pout
```

**qkumba-style:** Create a `close_pipeline` routine that closes both and returns the remaining FDs.

**The violation:** Convention says "each resource has its own cleanup function." qkumba says "when two resources are always cleaned up together, they should have a combined cleanup."

### Breadbin Application: Kernel init sequence

In `kmain`, the kernel init sequence is:
```assembly
jsr kbd_init
jsr con_init
jsr mem_init
jsr proc_init
jsr file_init
jsr blk_init
```

**qkumba-style:** What if these were combined into a single `kernel_init` routine that does all of them in order? The individual init functions could still exist for testing, but the entry point would be fused.

**The violation:** Convention says "each subsystem has its own init." qkumba says "when init is always sequential, fuse it."

## Technique 6: The Stack Depth is Bounded

### Fire Demo Example
The RNG seed on the stack works because the RNG is inlined and the stack depth is bounded by the algorithm structure. Each iteration pushes and pops exactly one byte.

### Breadbin Application: Shell Pipeline State

In `sh.s`, the pipeline state machine could use the stack for `last` and `tmpb` because the pipeline depth is bounded (max 8 stages). Each stage pushes state, and the final stage pops it.

**The violation:** Convention says "pipeline state belongs in zero page." qkumba says "when depth is bounded, use the stack."

## VERIFICATION
All 6 techniques are applicable to Breadbin. Each violates a convention but is justified by a clear trade-off.

## TRADE-OFFS
Each technique trades readability for resource efficiency. The key is to document WHY the convention was violated so future maintainers understand the reasoning.

## GENERAL PRINCIPLE
**"Break conventions when the machine gives you a resource that the convention hides."**

The six foundational techniques:
1. Stack as mutable storage (not just return addresses)
2. ROM/kernel side effects as protocol (not noise)
3. Data encodes algorithm (not just values)
4. Code/data duality (not separate)
5. Operation fusion (not separate calls)
6. Bounded depth = stack resource (not zero page)

## DECISION
**Adopt all six techniques as mental models. Apply them to Breadbin where the trade-off is clear.**
