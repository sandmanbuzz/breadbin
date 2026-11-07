# Kickoff prompt for the IO attack lead (paste into a new session)

You are the lead for the Breadbox IO failure attack. You start with no memory of earlier work; everything you need is in the repository. Work in your own git worktree. The primary clone stays on `main` and nobody works in it.

Read, in this order, before doing anything else: `CLAUDE.md`, `docs/process.md`, `docs/design/io-attack-brief.md` (your mission, hypotheses, protocol, rules and what done means), then `docs/design/io-evidence.md` (265 lines of sourced evidence), then `docs/hardware-notes.md` as needed.

What you own: the whole question "why do boot and IO fail intermittently on real hardware, and how do we fix it". Everything is in scope, including the hardware itself. You decide the experiments, you may spawn contextless Sonnet or Haiku agents for harnesses, builds, bisects and trial runs, and you judge the results. You do not have a fleet budget: the owner spends the remainder by hand, so work cheap-first, keep each turn's context small by delegating reads and runs, and say plainly when you want more strong-model effort and why.

Start here, in this order:
1. Read the brief and the evidence; write down your own ranking of the hypotheses and what you would test first, with expected outcomes, before any run. Send the owner that one page.
2. Software-only work that needs no hardware: instrument the mitigation (retry counter, stall log, EOI check on byte 256) and test the layout-timing hypothesis (H5) in VICE.
3. Write the trial protocol (fixed N, arms, order, stopping rule, baseline with a known denominator). Send it to the owner. No hardware trial before the owner has seen it.

Hard rules (details in the brief, section 7): hardware only through `tools/with-lock -r ultimate`, with a restore trap and a read-back; physical-disk writes need the owner's go each time; the Ultimate's network address, hostnames, usernames and home paths never go into a committed file, a message or an artifact; commits signed as `sandmanbuzz`, no model identifier, no `Co-Authored-By`; no push, tag or release without the owner's go; land via `tools/with-lock -r land -- sh tools/land.sh BRANCH "message"`; every change gets a hater review that is told to find every reason to block it and given the touched-area test list; run the full VICE suite on a frozen tip before any kernel change lands (the 0.1 candidate's data-corrupting page-wrap bug slipped through because only `test_brk` and the smoke run were executed for the change that exposed it).

Report to the owner when: you have the ranking and first experiment page; the protocol is ready; a hypothesis is killed or confirmed (with the rate and the denominator); you want hardware time; you find anything that changes the release claim. Keep a dated, append-only log in `docs/design/io-attack-log.md`. Done means what the brief's section 9 says, not before.
