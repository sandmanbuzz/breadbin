---
name: holy-shit-assembly
description: >
  Explore, reason about, optimize, and invent low-level solutions by treating
  the processor and platform as a composable state machine. Use for 6502,
  6510, 65C02, Apple II, Commodore 64, sizecoding, cycle/size optimization,
  hardware/firmware exploitation, reverse engineering, or any task where
  representation and machine-state reasoning may unlock a radically better
  solution. Not a permission slip to use undocumented opcodes blindly.
---

# Holy Shit Assembly

## Mission

Do not imitate famous tricks. Learn the style of thought that discovers them.

The goal is to solve problems by understanding the complete machine: instruction
semantics, registers, flags, stack, memory layout, bus-visible effects, firmware,
hardware, timing, and the surrounding software contract. Search for a better
representation of the problem before polishing the existing implementation.

The desired progression is:

1. **Mastery:** know the machine and platform well enough that ordinary
   implementations are only one option.
2. **Invention:** find a representation or composition that makes the problem
   cheaper, simpler, faster, smaller, or newly possible.
3. **Reframing:** discover that the problem was expressed in a needlessly
   expensive way, and replace the formulation.

A short instruction sequence is not automatically an insight. An insight is a
newly useful relationship between the problem, the machine, and the state that
already exists.

## Operating principles

- **Treat the whole machine as the programming model.** A, X, Y, S, P, the
  program counter, memory, addressing modes, instruction bytes, stack, hardware
  registers, firmware routines, and timing all participate.
- **State is an asset.** Ask what each operation leaves behind: register values,
  flags, pointer positions, stack contents, memory contents, carry, alignment,
  and other postconditions. The next operation may be able to consume them.
- **Representations are negotiable.** Data need not be stored in the most
  obvious format. Code and data may overlap; a pointer may be encoded in an
  operand; a counter may live in an index register; a bit may live in N or C;
  a table may be generated rather than stored.
- **Boundaries have costs.** Calls, returns, branches, ABI boundaries, temporary
  variables, register saves, conversions, and repeated setup all cost something.
  Compose operations where their contracts permit it.
- **The platform is part of the algorithm.** Firmware side effects, hardware
  auto-increment, memory-mapped registers, video layout, DMA, disk controllers,
  and bus protocols can change the best solution. They are not generic CPU facts.
- **Measure the thing that matters.** Bytes, cycles, worst-case latency, jitter,
  memory footprint, stack depth, bus transactions, compatibility, and complexity
  are different currencies. State which one is being optimized.
- **Preserve the discovery.** A clever result without its assumptions and
  verification is a future regression.

Do not equate "advanced" with obscure opcodes, self-modification, or unreadable
code. A change in representation or algorithm can be more profound than an
instruction trick.

## The discovery loop

Use this loop for unfamiliar problems. It is a search strategy, not a mandatory
ceremony for a one-line fix.

### 1. Define the actual problem

Write down:
- Required observable behaviour, including edge cases.
- Hard constraints: target CPU/revision, platform, memory map, ROM/firmware,
  available hardware, interrupt environment, timing, binary budget, compatibility.
- Soft objectives and their relative value: size, speed, latency, smoothness,
  memory, portability, simplicity, robustness, power.
- What may change and what must remain invariant.

Do not assume the current code's algorithm, data layout, or interfaces are sacred.
Do not optimize an incidental metric while missing the user's real constraint.

### 2. Establish a baseline

Inspect the implementation, call sites, linker map, disassembly, memory map,
tests, and platform documentation. Measure before changing it.

Record at least the relevant baseline metric and exact build/configuration.
For cycle work, state whether counts are hand-derived, emulator-measured, or
hardware-measured. For size work, distinguish source size, linked bytes, tables,
relocations, BSS, alignment, and load-image overhead.

### 3. Build a machine-state inventory

For each relevant routine and path, identify:
- Entry state: A/X/Y, flags, S, interrupt/decimal state, pointers, memory.
- Exit state: what is guaranteed, what is merely incidental, what is clobbered.
- Useful postconditions: carry, N/Z/V, index values, pointer position, known
  zero/nonzero values, alignment, page crossing status.
- Ownership and lifetime of scratch locations, stack bytes, zero page, and
  self-modified operands.
- Interrupt, reentrancy, concurrency, and asynchronous hardware interactions.

Look at the instruction sequence, not only individual instructions. An
instruction's result may be useful to its successor even if it looks odd alone.

### 4. Search the opportunity space

Ask these questions before reaching for a familiar implementation.

**State and flags**
- Can a prior result be reused instead of recomputed?
- Does a compare, shift, add, subtract, load, or branch already establish the
  flag needed by the next operation?
- Can carry/overflow/negative/zero encode a condition without a separate byte?
- Can a routine return a useful value in A/X/Y/P as part of its contract?
- Can a caller avoid restoring state it already knows?

**Control flow**
- Can fall-through replace a jump?
- Can a conditional branch use a flag already available?
- Can a branch, return, or dispatch be encoded in existing data or stack state?
- Can routines be composed, tail-called, or arranged to share an epilogue?
- Can layout eliminate a branch rather than merely shorten it?

**Memory and representation**
- Can code bytes double as constants, tables, pointers, or writable state?
- Can the load address or initial memory contents provide required values?
- Can data be arranged to avoid high-byte updates, carry propagation, or
  address calculations?
- Can page alignment, page boundaries, wraparound, or zero-page addressing
  simplify the algorithm?
- Can two variables share storage because their lifetimes do not overlap?
- Can a table be replaced by arithmetic, or arithmetic by a table?
- Can a value be stored in a form that makes its consumer cheaper?

**Registers and stack**
- Can X or Y replace a memory variable?
- Can stack order or stack contents become an implicit parameter, pointer,
  dispatch table, or temporary?
- Can pushes/pulls be combined with control flow?
- Is a subroutine boundary necessary, or is it only convention?
- Can stack use reduce memory traffic without exhausting call depth or
  interfering with interrupts/context switching?

**Hardware and firmware**
- Does a documented ROM routine leave useful registers or pointers behind?
- Does hardware maintain a pointer, increment an address, latch state, or
  perform a transformation for free?
- Can an existing display, disk, timer, DMA, or serial mechanism perform work?
- Is there a side effect that can replace bookkeeping?
- Is that side effect stable across the actual target models and ROM revisions?

**Algorithm and search**
- Is there a different algorithm with a better cost profile?
- Can preprocessing move work out of a hot path?
- Can a lookup table, recurrence, incremental update, approximation, or
  invariant replace repeated general computation?
- Can the required result be obtained without computing the intermediate
  result the obvious algorithm produces?
- Are there constraints or output freedoms that permit a cheaper solution?

Generate multiple hypotheses. Include a conservative option, a radical option,
and (when appropriate) an option that changes the representation or algorithm.

### 5. Predict before prototyping

For each candidate, predict:
- Bytes and cycles, including setup and teardown.
- Best, average, and worst-case timing where relevant.
- Memory, stack, and zero-page use.
- Effects on flags/registers and calling conventions.
- Hardware/ROM dependencies and compatibility.
- New hazards: reentrancy, interrupt races, page crossings, bus side effects,
  alignment, decimal mode, or timing sensitivity.
- Complexity cost: how hard will a future agent be able to verify and modify it?

If the prediction is wrong, that is useful information. Record why.

### 6. Prototype in isolation

Build the smallest experiment that can falsify the hypothesis. Keep experiments
separate from production changes until their value and hazards are understood.

Use a minimal harness when possible. Test the actual CPU/platform, or clearly
label emulator-only evidence. Disassemble the result. Compare against a
reference implementation or known-good output. Exercise boundary conditions.

### 7. Measure and challenge

Compare against the baseline using the same toolchain and conditions.

For every claimed win, ask:
- Did total code size improve, or did bytes move into tables, setup, or BSS?
- Did the hot path improve while cold paths regressed?
- Did average cycles improve while worst-case latency or jitter got worse?
- Did an optimization depend on a lucky linker placement?
- Did a side effect break another consumer?
- Does the result survive another CPU revision, ROM, emulator, or real machine?
- Is the gain worth the new invariant and maintenance burden?

A clever implementation that cannot be reproduced is not yet a result.

### 8. Promote knowledge, not just code

Record the general principle separately from the target-specific implementation.
A useful technique entry explains where to look for similar opportunities in
other code or on other machines.

A failed experiment is a valid contribution if it establishes a boundary,
invalidates an assumption, or saves the next investigator time.

## Runbooks

These are search procedures. Use the ones relevant to the problem; combine them
when a discovery crosses categories.

### Runbook: State economy and postcondition chaining

**Look for:** repeated loads, stores, clears, compares, flag-setting, pointer
setup, register saves/restores, and routines that discard useful exit state.

**Procedure:**
1. Trace the state through the complete path, instruction by instruction.
2. Mark every value and flag that is known at each point.
3. Ask whether the next operation can consume that state directly.
4. Consider strengthening routine contracts to promise useful postconditions.
5. Remove redundant setup only after proving all callers satisfy the contract.

**Typical opportunities:** carry chaining for multi-byte arithmetic; use compare
or shift flags directly; return status in a register/flag; skip save/restore when
the selected process is already current.

**Hazards:** undocumented clobbers, decimal mode, interrupt entry, callers that
depend on old flags, and ABI compatibility.

### Runbook: Flag alchemy

**Look for:** boolean variables, branches following arithmetic, redundant
CMP/AND/TST operations, and values whose only purpose is to communicate a
condition.

**Procedure:**
1. Identify the condition's lifetime and all consumers.
2. Determine which instructions already establish the required flag.
3. Explore encoding the condition in a bit position that maps to N/Z/C/V.
4. Check whether the chosen flag survives intervening instructions.
5. Check whether the value's non-flag bits matter.

**Canonical example:** Michael Steil's analysis of Wozniak's Apple I BASIC
describes storing a boolean in bit 7, clearing it with LSR memory, and testing
it with BIT plus BPL. The point is not "always use bit 7"; it is to choose a
representation whose natural mutation and observation instructions are cheap.

**Hazards:** flags are volatile shared processor state; BIT performs a memory
read and changes N/V/Z; memory-mapped reads may have side effects. Do not assume
a flag survives a call or an interrupt.

### Runbook: Control-flow sculpting

**Look for:** unconditional JMPs, branch-around blocks, repeated epilogues,
short dispatchers, and call chains that merely forward control.

**Procedure:**
1. Draw the control-flow graph and annotate incoming flag/state conditions.
2. Try fall-through layout before adding branches.
3. Check whether a branch condition already exists from useful work.
4. Consider tail calls, shared exits, return-stack dispatch, and instruction
   overlap where the target and stack contract make them valid.
5. Recompute branch reach, timing, and all entry paths after layout changes.

**Hazards:** JSR/RTS stack balance; branch range; interrupts; return-address
encoding; page-cross timing; code readability. Replacing JSR/RTS with JMP is
valid only when the callee's eventual RTS returns to the original caller with
the expected stack.

### Runbook: Memory sculpting and code/data dual use

**Look for:** duplicated constants, tables, temporary buffers, address
calculation, fixed load addresses, and RAM used for only one phase of a program.

**Procedure:**
1. Draw the memory map and object lifetimes.
2. Identify values already present in code bytes, load images, ROM, or hardware.
3. Explore overlays between non-overlapping lifetimes.
4. Explore table layouts that eliminate high-byte arithmetic or pointer updates.
5. Check whether instruction operands can serve as data, or vice versa.
6. Account for relocation, writable/executable requirements, and all readers.

**Hazards:** self-modifying code requires writable memory and instruction-cache
coherence on relevant architectures; memory-mapped I/O is not ordinary RAM;
overlays require proven non-overlapping lifetimes; zero page may be a public
resource for user programs.

### Runbook: Stack as a resource

**Look for:** temporary variables, parameter mailboxes, repeated pointer setup,
return dispatch, and values that are produced and consumed in strict LIFO order.

**Procedure:**
1. Draw the exact stack layout at every call boundary.
2. Determine ownership of each byte and maximum nesting depth.
3. Consider PHA/PLA, PHP/PLP, RTS/RTI, and return-address manipulation only
   against that explicit layout.
4. Compare stack traffic against the memory/register alternative.
5. Verify interrupt and context-switch behaviour.

**Hazards:** the 6502 stack is one page; stack tricks interact with calls,
interrupts, BRK/RTI, and scheduler save areas. It is not free scratch RAM.

### Runbook: Addressing modes, alignment, and layout

**Look for:** repeated 16-bit pointer arithmetic, indexed loads/stores, page
crossings, loops over fixed-size records, and tables with predictable ranges.

**Procedure:**
1. Determine which addressing modes dominate the hot path.
2. Re-layout data so index registers and page boundaries do useful work.
3. Consider page-aligned tables, split high/low tables, descending counters,
   and wraparound where mathematically valid.
4. Check page-cross penalties and branch timing.
5. Verify linker placement rather than relying on an accidental address.

**Hazards:** zero-page pointer wrap, indexed page crossings, 6502 indirect-JMP
page-wrap behaviour, and differences between NMOS and CMOS derivatives.

### Runbook: Self-modification and specialization

**Look for:** repeated indirect addressing, invariant operands, loops that
recompute a pointer, and code that repeatedly interprets a stable parameter.

**Procedure:**
1. Identify the invariant that can be compiled into the instruction stream.
2. Patch the smallest operand or opcode necessary.
3. Separate initialization cost from steady-state savings.
4. Define ownership: who may patch it, when, and whether interrupts can observe
   a partially updated instruction.
5. Provide a non-SMC fallback if the code may execute from ROM or shared memory.

**Hazards:** ROM, reentrancy, interrupts, concurrent execution, relocation,
write protection, code sharing, and modern instruction caches. Self-modification
is a technique with a contract, not a default style.

### Runbook: Firmware and hardware side effects

**Look for:** ROM calls, device registers, status polling, hardware-maintained
pointers, DMA, video/drive routines, and repeated software work that hardware
may already perform.

**Procedure:**
1. Identify the exact platform, model, ROM revision, and entry conditions.
2. Read source/disassembly or reliable technical documentation for the routine.
3. Record documented outputs and observed incidental side effects separately.
4. Build a probe that checks the side effect on each supported target.
5. Decide whether the dependency is acceptable; isolate it behind a named
   platform contract if adopted.

**Example:** in Deaterage's 64-byte Apple II fire demo, qkumba noticed that the
Apple II SCROLL routine left BAS2L:BAS2H pointing at $07D0. That observation
saved address setup. The optimization history also records a real-hardware
difference involving MIXCLR, and experiments that failed to pay off. This is
the complete lesson: inspect side effects, test the actual hardware, and keep
the failed branches of the search visible.

**Hazards:** firmware versions, machine variants, undocumented entry state,
memory corruption, timing, and destructive I/O. Never generalize an Apple II
ROM fact to the C64 or to "the 6502".

### Runbook: Undocumented opcodes

**Look for:** only after the ordinary instruction set, algorithm, and
representation have been explored—or when a measured target-specific benefit
justifies the risk.

**Procedure:**
1. Identify the exact silicon family and revision. "6502-compatible" is not a
   sufficient target specification.
2. Classify the opcode as stable, unstable, or undocumented-but-defined only
   for a particular implementation.
3. Read cycle, bus, flag, and addressing behaviour from authoritative sources
   and independent tests.
4. Build a minimal executable probe for each relevant opcode/addressing mode.
5. Run it on every supported real target and emulator; retain the raw results.
6. Keep the opcode behind a macro/feature gate with a documented fallback.
7. Revisit whether the measured win is worth the compatibility and debugging
   cost.

**Never:** infer compatibility from one emulator; assume all NMOS parts behave
like all 6510s; use unstable opcodes in shared production code without an
explicit hardware contract; or treat "illegal" as synonymous with "free".

Breadbin already has a useful starting pattern in
experiments/illegal-ops/: a standalone test program checks known stable
families and reports failures. Extend that discipline rather than replacing it
with confidence.

### Runbook: Algorithmic reframing

**Look for:** large tables, expensive multiplies/divides, repeated calculations,
precision that may not be needed, and operations performed only because the
current data representation makes them convenient.

**Procedure:**
1. State the mathematical or behavioural requirement independently of code.
2. Determine which output precision and behaviour are actually observable.
3. Explore recurrence, incremental update, lookup, interpolation, symmetry,
   precomputation, bit slicing, and algebraic decomposition.
4. Move work between initialization and the hot path deliberately.
5. Compare complete cost, including table generation, storage, and precision
   loss.

**Example:** Deaterage's Star Path optimization history is a particularly good
study: it records changing algorithms, table generation, multiplication,
self-modified operands, and the size/cycle trade-offs across many iterations.
The sequence matters more than any single final trick.

### Runbook: Experimental archaeology

**Look for:** old code, opaque binaries, strange firmware assumptions,
protection schemes, unexplained timing, or behaviour that contradicts
documentation.

**Procedure:**
1. Preserve an untouched reference image/binary and record provenance.
2. Observe behaviour before explaining it.
3. Form competing hypotheses and design probes that distinguish them.
4. Use disassembly, tracing, controlled patching, hardware tests, and differential
   comparison.
5. Automate repeated discoveries only after the manual process is understood.
6. Keep evidence, inference, and speculation visibly separate.

**Example:** 4am's Passport project is an excellent model of turning accumulated
reverse-engineering knowledge into a systematic tool. Its history describes a
progression from manual RWTS capture, to automation after repeated cracks, to
automated patching, and ultimately a broad verification/copy system. The lesson
is not merely clever disassembly: repeated expert work can reveal a family of
problems, which can then be represented as a reusable recognizer and repair
pipeline.

### Runbook: Measurement and proof

**Look for:** any claim that something is faster, smaller, safer, more compatible,
or "obviously equivalent".

**Procedure:**
1. Define the metric and its measurement method.
2. Record toolchain, build flags, CPU/platform, emulator/hardware, and input.
3. Prove semantic equivalence or enumerate intentional behavioural changes.
4. Measure the complete path and relevant worst cases.
5. Repeat the measurement and retain raw output or reproducible commands.
6. Have a second agent independently inspect the reasoning for hidden
   assumptions.

**Distinguish:** hand-counted cycles, emulator cycles, hardware timing,
instruction bytes, linked image bytes, resident memory, transient memory, and
system-wide resource cost. Never silently substitute one for another.

## Architecture and platform cautions

"6502" names a family, not a single interchangeable machine.

Before applying a technique, identify:
- NMOS 6502 versus 6510 versus 65C02/65SC02 versus 65816.
- Exact chip or FPGA implementation and relevant revision.
- C64 versus Apple II versus NES versus other platform.
- Memory map, ROM, I/O decode, banking, video/audio hardware, and bus timing.
- Assembler syntax, linker placement, executable format, and calling convention.
- Interrupt sources, handler behaviour, and whether code is reentrant.
- Emulator fidelity and known deviations.

Examples of non-portable assumptions:
- Undocumented opcode behaviour.
- Decimal-mode arithmetic details.
- Indirect JMP page-boundary behaviour.
- ROM routine addresses and side effects.
- Memory-mapped I/O read/write semantics.
- Timing, raster, DMA, and bus contention.
- Zero-page ownership and firmware scratch locations.

For breadbin specifically:
- Treat the 6510/C64/Ultimate target contract as explicit and testable.
- Preserve zero page as a resource for user programs; do not consume it casually
  because a local optimization is convenient.
- Account for process context save/restore, interrupt entry, scheduler ownership,
  stack-save regions, and syscall ABI.
- Prefer isolated probes and experiments before introducing target-specific
  assumptions into resident kernel code.
- A win in a demo or standalone probe does not automatically justify a kernel
  dependency.

## How to study a jaw-dropper

When reading an expert artifact, do not merely annotate the instructions. Produce
a discovery note with these questions:

1. What was the original problem and budget?
2. What is the baseline implementation?
3. What did the author notice that was not obvious?
4. Which assumptions did they reject or exploit?
5. What alternative representations or algorithms appear?
6. Which machine state is reused, and how?
7. Which side effects are intentional, incidental, or target-specific?
8. What experiments failed, and what did they teach?
9. What is the measured result, and how was it measured?
10. What general search heuristic can another agent reuse?
11. What new problem could this insight make tractable?

Do not claim an idea is novel merely because it is unfamiliar. Search the literature,
source repositories, demos, technical manuals, and prior art. Credit the people
whose work supplied the insight. Link to the exact source and relevant revision.
Do not copy substantial source code into project documentation without checking
its license and attribution requirements; explain the idea in your own words.

## Contribution format

For a technique, experiment, or discovery, use this compact record:

~~~text
TITLE
PROBLEM
BASELINE (code, bytes/cycles/resources, build and target)
OBSERVATION (what was noticed)
HYPOTHESIS (why it should work)
TRANSFORMATION (what changed)
INVARIANTS (what must remain true)
TARGET CONTRACT (CPU, model, ROM, memory map, interrupts, ownership)
RESULT (measured, not estimated; label estimates)
VERIFICATION (tests, emulator, hardware, disassembly, reproduction steps)
TRADE-OFFS (complexity, portability, timing, maintenance)
FAILED ALTERNATIVES (and what they taught)
GENERAL PRINCIPLE (portable lesson)
REVERSION / FALLBACK
SOURCES AND CREDIT
DECISION (adopt, reject, defer, retain as experiment)
~~~

Use VERIFIED / UNVERIFIED labels for factual claims. Separate:
- **Fact:** directly established by a source or experiment.
- **Observation:** directly seen in a particular run or machine.
- **Inference:** explanation consistent with the evidence.
- **Hypothesis:** untested prediction.
- **Speculation:** interesting possibility, not yet supported.

## Training exercises

Prefer exercises that teach a way of seeing, not rote reproduction.

1. **Postcondition audit:** take a small routine and annotate every useful
   register and flag value at each exit. Remove redundant setup in its callers.
2. **Flag-carried boolean:** represent a boolean in a bit position chosen for
   cheap mutation and testing. Compare code size, clobbers, and call contracts.
3. **Layout challenge:** implement the same loop with forward and reverse
   counters, page-aligned data, and alternative table layouts. Explain the
   differences.
4. **Memory lifetime map:** overlay scratch buffers whose lifetimes do not
   overlap. Prove the lifetimes from call graphs and interrupt paths.
5. **Firmware side-effect probe:** call a documented ROM routine, record all
   register/memory changes, and repeat across supported models. Do not rely on
   the result until differences are understood.
6. **Algorithm replacement:** take a table-heavy or multiply-heavy operation
   and explore recurrence, precomputation, approximation, and lookup alternatives.
7. **Illegal-op validation:** extend a standalone probe with expected A/X/Y,
   memory, flags, and bus-visible effects. Run on actual target variants.
8. **Blind optimization:** receive a problem statement and constraints without
   being told which technique to use. Produce at least three hypotheses and a
   measured comparison.

After an exercise, ask the agent to explain the discovery process and identify
which heuristic it would transfer to a completely different architecture.

## Source trail: start here

These are starting points, not a canon. Prefer primary artifacts, original
source, disassembly, manuals, and author-written optimization histories over
lists of tricks.

### Deaterage / VMW
- [Size Coding on the Apple II](https://www.deater.net/weave/vmwprod/demos/sizecoding.html)
- [Lovebyte 2021 sizecoding slides (PDF)](https://www.deater.net/weave/vmwprod/demos/lovebyte2021_sizecoding.pdf)
- [fire_qkumba.s](https://github.com/deater/dos33fsprogs/blob/master/demos/fire/fire_qkumba.s)
- [starpath.s](https://github.com/deater/dos33fsprogs/blob/master/demos/outline2025/starpath/starpath.s)
- Study the source's optimization histories, comments, and failed attempts,
  not just the final byte count.

### qkumba
- [Passport project history](https://github.com/a2-4am/passport)
- [Passport patchers and changelog](https://github.com/a2-4am/passport/blob/master/README.md)
- Follow attribution in source histories for qkumba's individual contributions.
  Inspect the actual patcher or routine and reconstruct the constraints it solves.

### 4am
- [Passport](https://github.com/a2-4am/passport)
- [Confessions of a Disk Cracker: the secrets of 4am](https://paleotronic.com/2018/06/15/confessions-of-a-disk-cracker-the-secrets-of-4am/)
- [Apple II Elite source variants, including the 4am crack](https://github.com/markmoxon/elite-source-code-apple-ii)
- Study the progression from repeated manual investigation to reusable
  recognition, verification, and patching systems.

### Cross-architecture sizecoding and algorithmic design
- [Mathieu Acher: Size Coding a Cinematic Experience Fitting Into 256 bytes](https://blog.mathieuacher.com/SizeCodingArtBuild/)
- [ilmenit/sizecoding](https://github.com/ilmenit/sizecoding)
- [CurlyWAS](https://github.com/exoticorn/curlywas)
- Use this work to study design-space exploration, compiler/toolchain effects,
  and algorithmic reframing—not as evidence about 6502 instruction semantics.

### Independent technique references
- [Michael Steil: Optimized Flags Code for 6502](https://www.pagetable.com/?p=29)
- [NESdev: 6502 programming tricks](https://www.nesdev.org/wiki/User:Zzo38/6502_programming_tricks)
- [NESdev: 6502 registers and flags](https://www.nesdev.org/obelisk-6502-guide/registers.html)
- [6502 idioms and speed](https://acwright.github.io/6502-DOCS/assembly/idioms)
- Treat community references as leads; verify claims against authoritative CPU
  documentation and target experiments.

## Definition of done

An agent using this skill should not simply produce shorter assembly. It should:
- State the problem and objective precisely.
- Inspect the full machine and platform contract.
- Identify useful state and challenge the existing representation.
- Generate competing hypotheses, including radical alternatives.
- Prototype safely and measure against a baseline.
- Verify target-specific behaviour and expose uncertainty.
- Explain the reusable principle behind the result.
- Leave enough evidence that another agent can reproduce, challenge, and extend it.

The ambition is not to write code that looks like the legends wrote it. It is to
develop ideas that would make an expert stop, inspect the machine, and think.
