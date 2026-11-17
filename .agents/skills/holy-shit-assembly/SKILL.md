---
name: assembly-codebase-work
description: >
  Read, understand, modify, debug, and extend existing 6502-family assembly
  code. Use before editing assembly routines, drivers, kernels, firmware-facing
  code, or tightly constrained low-level modules. Emphasizes preserving local
  contracts, understanding machine state and platform behavior, measuring
  changes, and leaving the code easier to reason about.
---

# Working in an Assembly Codebase

Assembly is not a collection of instructions waiting to be improved. It is a
conversation between routines, registers, flags, memory, hardware, timing, and
the people who have to keep the system working.

When entering an established codebase, your first job is to learn that
conversation. The code in front of you may be carrying assumptions that are
not written down: a flag left set for the next branch, a pointer deliberately
advanced past the last byte, a buffer reused after a phase transition, a
hardware register read whose side effect matters, or a routine whose apparent
output is only half its contract.

Do not begin by making the code look more familiar. Begin by finding out why it
looks the way it does.

The goal is not to preserve every historical oddity. It is to distinguish
accidental complexity from useful structure before changing either.

## Before touching a routine

Do this reconnaissance before editing, especially when the task sounds local
("fix this branch", "add a command", "change the retry loop") but the code is
old or hardware-facing.

### 1. Find the boundaries

Read the target routine in full, then follow its callers and callees far enough
to understand how it is used.

Establish:

- Every entry point, including indirect calls, vectors, jump tables, and
  interrupt paths.
- Inputs: registers, flags, stack layout, pointers, memory locations, and
  hardware state.
- Outputs: returned values, changed registers, flags, memory, pointer
  positions, and device state.
- Clobbers and preserved state, including anything callers rely on without
  declaring it.
- Error and exceptional paths, not just the happy path.
- Whether the routine can be interrupted, re-entered, called recursively, or
  run while another component owns the same memory.

A routine's contract is the complete set of facts its callers need to know.
The label and comment may describe only a fraction of it.

### 2. Read the surrounding dialect

Every assembly codebase develops a local dialect. Learn it before introducing
a new one.

Look at nearby routines for:

- Register and flag conventions.
- Zero-page and scratch-memory ownership.
- Stack discipline and calling conventions.
- Branch layout and common exit patterns.
- Error propagation and retry conventions.
- Assembler macros, pseudo-instructions, and linker assumptions.
- Naming, comments, alignment, and data placement.
- Existing tests, probes, debug hooks, and build targets.

Prefer an established local convention when it is sound. If it is not sound,
understand who depends on it before replacing it. Consistency is valuable, but
not at the price of perpetuating a demonstrated bug.

### 3. Establish what is actually built

Do not reason from source alone when placement or encoding matters.

Find the relevant build command and inspect the generated artifact. When useful,
consult the linker map, labels, listing, disassembly, binary diff, and memory
map. Record the baseline before changing anything.

Know which assembler and options are in use. Syntax, macro expansion, branch
relaxation, zero-page selection, segment placement, and expression evaluation
can all affect the machine code.

For performance or size work, identify the actual metric:
- Source lines are not bytes.
- Instruction count is not cycle count.
- A shorter routine may require a larger table or more setup.
- A faster common path may worsen worst-case latency.
- A local saving may move cost into callers or interrupt handling.

If you cannot reproduce the current build, do not pretend you have a reliable
baseline.

### 4. Identify the real machine

"6502" is not a complete target description.

Establish the processor family and implementation, machine model, memory map,
ROM/firmware version, I/O behavior, clock/timing environment, and emulator or
hardware used for verification.

Do not transfer assumptions casually between NMOS 6502, 6510, CMOS derivatives,
Apple II, C64, disk drives, or FPGA implementations. Decimal mode, undocumented
opcodes, indirect-JMP behavior, bus cycles, memory-mapped I/O, and ROM side
effects are not universally interchangeable.

For a driver, the device is part of the machine. Read the device documentation
and existing low-level access code. Determine which reads acknowledge or clear
conditions, which writes start operations, which registers latch values, and
which status bits are transient. A register access may be an action, not merely
a load or store.

## Read the code as a state transition

When a routine is difficult to understand, annotate what is true at each
important point. Track more than the obvious data value.

For each path, follow:

- A, X, Y, S, and the relevant bits of P.
- Pointer values and whether they point at the current, next, or last item.
- Memory values, including scratch bytes and self-modified operands.
- Carry propagation, sign, zero, overflow, and other flag lifetimes.
- Stack contents and return-address state.
- Interrupt enable state and any assumptions about interrupt timing.
- Device state and effects of reads/writes.
- Which component owns each temporary location at that moment.

An instruction has both an immediate result and a postcondition. The postcondition
may be the important part. A compare can leave exactly the carry a later
operation needs. An increment can establish a branch condition. A routine can
return with a pointer already advanced, or a register containing a useful
remainder. Do not erase that information by reflexively reloading, clearing,
comparing, or restoring state.

Likewise, do not assume a flag is available merely because it was set earlier.
List every intervening instruction and call. Flags are shared, volatile state;
some instructions replace them, some preserve selected bits, and interrupts
can change the picture.

When the code seems unnecessarily indirect, ask what its state is buying.
When it seems unnecessarily clever, prove what that cleverness is buying.

## Follow the data, not just the control flow

Draw the path of important bytes through the routine and its callers.

Ask:

- Is a value copied because two consumers need it, or because the original
  representation is inconvenient?
- Does a pointer refer to the beginning, end, or next free byte?
- Is a counter inclusive or exclusive? Does wraparound terminate the loop?
- Can a table's layout make indexing or page handling simpler?
- Are two buffers live at the same time, including on error and interrupt
  paths?
- Is a byte in code, a load image, a return address, or a hardware register
  already carrying information that another variable duplicates?
- Does a routine need the computed value, or only a property of that value?
- Can a later phase reuse storage that an earlier phase no longer needs?

Memory overlays and code/data sharing can be sound, but only when lifetimes,
ownership, mutability, and all asynchronous paths are understood. Zero page,
stack space, and hardware registers are not free scratch space simply because
they are convenient.

A representation should be judged by the work it makes cheap for its consumers,
not by how natural it looks in a source listing.

## Respect the machine's existing work

Before implementing software bookkeeping, check whether the processor,
firmware, or device already maintains the state you need.

Examples worth investigating include:

- Hardware-maintained address or data pointers.
- Device status and completion state.
- ROM routines that leave registers or pointers in useful states.
- Page alignment and addressing modes that eliminate arithmetic.
- Carry and other flags that communicate a result without a separate byte.
- Stack order that naturally carries parameters or dispatch information.
- Data layouts that allow an index register to do useful work directly.

Treat incidental behavior as a dependency, not a lucky discovery to rely on
silently. Verify it against the exact hardware and firmware versions that the
project supports. If adopted, document the entry conditions, observed effects,
and fallback or compatibility boundary.

Never generalize a behavior observed on one 6502-family machine into a property
of every 6502-family machine.

## Make the smallest change that proves the point

Once the contract and state flow are understood:

1. State the intended behavior and the invariant that must remain true.
2. Identify the narrowest change that can establish the behavior.
3. Consider whether the change alters a caller-visible register, flag, pointer,
   memory, timing, or device-state contract.
4. Check all entry and exit paths, including errors and interrupts.
5. Build and test before broadening the change.

Do not refactor a whole routine merely because you have now understood it.
Keep unrelated cleanup separate so that a regression has a small search area.

If a larger redesign is justified, first write down the current contract and
the proposed replacement contract. Make the boundary explicit; do not let a
new implementation quietly change the meaning of an old interface.

## Look for simpler work, not just shorter instructions

When a routine is genuinely expensive or awkward, widen the search before
hand-optimizing its current instruction sequence.

Useful questions include:

- Can repeated work move into initialization or a less frequent path?
- Can a table replace arithmetic, or arithmetic replace a table?
- Can a recurrence or incremental update replace recomputation?
- Can a condition be carried in a flag or an existing bit?
- Can adjacent routines share a useful postcondition instead of saving and
  restoring state at every boundary?
- Can data be laid out to avoid pointer adjustment or page crossing?
- Can a branch disappear through better control-flow layout?
- Can two phases share storage because their lifetimes do not overlap?
- Can the required result be obtained without calculating an intermediate
  value the obvious algorithm would produce?
- Is the existing algorithm solving a more general problem than this caller
  actually needs?

Generate more than one candidate when the cost is meaningful. Include a
conservative change and at least one alternative that changes the data layout,
the division of work, or the algorithm itself. Predict the costs before
implementing them.

Do not reach for self-modifying code or undocumented opcodes as a substitute
for understanding the problem. They may be appropriate under an explicit target
contract, but they add obligations around memory writability, interrupts,
reentrancy, silicon behavior, and verification.

## Driver work: additional obligations

A driver sits between software expectations and hardware behavior. Changes that
look local can affect command sequencing, error recovery, timeouts, and the
meaning of device status.

Before modifying a driver, identify:

- The device state machine and legal command sequences.
- Which status reads are destructive or acknowledge pending conditions.
- Which writes initiate work or change device mode.
- Busy, ready, error, timeout, and reset behavior.
- Whether status can change between a test and the following action.
- The ownership and lifetime of command, data, and result buffers.
- Whether interrupts, polling, or both are used, and who owns the device.
- Retry limits and whether retries are safe after partial completion.
- What the caller expects on success, failure, and timeout.
- Which behaviors are hardware facts and which are conventions imposed by
  this driver.

Do not "simplify" a status sequence until you know whether the sequence itself
is part of the device protocol. Do not add a retry without determining whether
the previous command may already have taken effect. Do not reuse a buffer
because the happy path has finished with it if an interrupt or error path can
still refer to it.

When device documentation is incomplete, build a probe or trace the existing
implementation. Record the observation and target conditions. Keep uncertainty
visible.

## Verify the change at the right level

Choose verification that matches the claim.

- **Assembly/build:** does it assemble with the project's actual toolchain?
- **Binary:** are the bytes, addresses, relocations, and branch targets what
  you intended?
- **Routine:** are register, flag, stack, and memory contracts preserved?
- **Protocol:** are device command sequences and status transitions valid?
- **System:** do callers, scheduling, interrupts, and error recovery still work?
- **Target:** does it behave on the supported hardware, not only in an emulator?

For cycle claims, say whether the count is derived, emulator-reported, or
hardware-measured. For size claims, distinguish routine bytes from tables,
setup, alignment, and total image size.

Use boundary cases deliberately: zero, one, maximum count, page crossing,
wraparound, timeout, missing device, unexpected status, repeated invocation,
and interruption at vulnerable points. Pick the cases that match the routine;
do not treat a passing happy-path test as proof of a driver.

If the change depends on a particular ROM side effect, silicon behavior, or
device quirk, add a focused probe or regression test where practical.

## Leave the next person a map

Comments should explain why a non-obvious choice is correct, not narrate each
instruction. A useful comment records a contract, invariant, hardware fact,
or reason a tempting alternative is wrong.

For a surprising routine, document:

- Required entry state.
- Guaranteed exit state and clobbers.
- Memory and stack ownership.
- Interrupt/reentrancy assumptions.
- Hardware/ROM dependencies.
- Timing or placement constraints.
- The reason for any unusual representation or instruction sequence.

When making a nontrivial change, leave a compact record:

```text
INTENT: what behavior or cost is being changed
CONTRACT: inputs, outputs, clobbers, invariants
OBSERVATION: what the existing code or hardware does
CHANGE: what was altered and why
TARGET: CPU, machine, ROM/device revision, build configuration
RESULT: measured outcome; label estimates
VERIFICATION: tests, probes, hardware/emulator, reproduction steps
TRADE-OFFS: complexity, compatibility, timing, memory
REJECTED: plausible alternatives and why they were not chosen
```

Separate fact from observation, inference, and hypothesis. "The manual says"
is different from "I saw this on one drive". "This should preserve carry" is
different from a test that proves it across every path.

Preserve failed experiments when they establish a useful boundary. A future
maintainer should not have to rediscover why an attractive alternative was
rejected.

## When an oddity deserves investigation

A strange sequence is not automatically a bug, and an elegant sequence is not
automatically correct.

If you encounter code that appears redundant, backwards, overcomplicated, or
dependent on an obscure side effect:

1. Identify exactly what appears unnecessary or surprising.
2. Trace all inputs, outputs, flags, pointers, and memory effects.
3. Search callers and adjacent routines for dependencies.
4. Check history, comments, tests, linker placement, and platform documents.
5. Form at least two explanations before changing it.
6. Construct a small experiment that distinguishes those explanations.
7. Only then simplify, preserve, or replace it.

The same discipline applies to code that looks conventional. Familiarity is
not evidence that its algorithm or representation is appropriate.

## A practical review checklist

Before committing an assembly change, ask:

- [ ] Have I read the whole routine and enough of its callers/callees?
- [ ] Do I know the actual CPU, platform, device, and toolchain?
- [ ] Have I identified register, flag, stack, memory, and hardware contracts?
- [ ] Have I checked interrupt, reentrancy, and error paths?
- [ ] Do I understand the local code conventions?
- [ ] Do I have a reproducible baseline where the change affects size or speed?
- [ ] Have I checked the generated machine code where placement or encoding matters?
- [ ] Have I tested meaningful boundary and failure cases?
- [ ] Have I separated hardware observations from assumptions?
- [ ] Have I documented any new invariant or unusual dependency?
- [ ] Can the next person tell why this code is correct without reconstructing my entire investigation?

The standard is not "the diff is small" or "the routine is clever". The standard
is that the change is correct within its real machine contract, its costs are
understood, and the next person has a better chance of understanding the system
than you did when you arrived.
