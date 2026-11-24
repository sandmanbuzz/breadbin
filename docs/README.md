# Docs index

Start with `CLAUDE.md` (build, tests, decisions), then `process.md`, `wip.md` and `roadmap.md`.

**Naming.** The outward name of this fork is **Breadbox**: the boot banner, the README and docs that face users and readers should say Breadbox. The guts keep the Breadbin names (`build/breadbin.d64`, the `BREADBIN` boot file, `include/breadbin.inc`, `BREADBIN_*` variables), for continuity with upstream, which we stay in contact with. No branding pass has been done; converge docs and labels on Breadbox as they are touched. Upstream is always "Breadbin".

| Class | Files |
|---|---|
| Live: direction and state | `roadmap.md`, `wip.md`, `process.md`, `size-ledger.tsv`, `program-size-ledger.tsv` |
| Live: how to build and test | `testing.md`, `ci.md`, `filesystem.md`, `webdemo.md`, `claude-quota.md` |
| Live: user books (examples run by `tools/test_manual.py`) | `manual/` |
| Live: record of findings | `hardware-notes.md` (append-only), `design/io-attack-log.md` (append-only, closed) |
| Reference: designs in force or in progress | `design/pvm.md`, `design/basic.md`, `design/fast-io.md`, `design/next/*`, `design/size-spike.md`, `design/soft80-*.md`, and the rest of `design/` |
| Reference: research | `design/research/next/` (the shared-library and ABI studies behind roadmap E2), `design/research/TEMPLATE.md` |
| Closed investigations kept for their tools and evidence | `design/io-*.md`, `design/iec-failed-send.md`, `../experiments/iec-stall/` (the harness and probes are still used) |
