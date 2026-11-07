# Quota strategy

Draft for owner review. Inference quota is the binding constraint on the fleet. This page says how we spend it. Numbers come from `tools/claude-quota` (see `docs/claude-quota.md`); the owner's facts are marked as such.

## Facts

- Two buckets matter: `five_hour` (a rolling window) and `seven_day` (resets weekly). `now` and `status` report both, with a burn projection (`will_cap_before_reset`).
- Owner's facts: the weekly bucket stood near 75% at day start; work runs in bursts of about 3 hours inside the 5-hour windows; the fleet owns the product for the window.
- First live reading (2026-11-07 05:11 UTC): five_hour 44%, seven_day 86%, weekly reset 2026-11-09 05:00 UTC. About 14% of the week is left for roughly 48 hours. At the day's observed pace (about 11 points) that is tight: weekly, not the 5-hour window, is the constraint.
- The burn estimate needs about 5 minutes of history and is a straight-line fit. Treat "unknown" as "not safe".

## What the weekly bucket allows

Think in a daily allowance, not a window allowance: `allowance = (100 - seven_day) / days_to_reset`. Re-compute at every checkpoint. If the allowance is below the last day's observed spend, we are over budget and drop one tier below.

## Tiers (set by the tighter of the two buckets)

| Tier | Trigger | What runs |
|---|---|---|
| Green | seven_day projected at reset under 85%, five_hour under 70% | Normal sprint: parallel lanes, hater reviews on kernel, bus and data-loss changes, full suite at milestones |
| Yellow | projected 85-95%, or five_hour 70-85% | One lane at a time. Small cheap-model agents for analysis, ports, fixes. No new exploratory work. Reviews only for correctness, data loss, kernel and bus |
| Red | projected over 95%, or seven_day over 90%, or five_hour over 85% | Close what is in flight and commit. No new fan-out. Read-only checks, docs, landings of finished branches. Wait for the window to roll |
| Floor | seven_day over 97% | Stop. Land only what is finished and tested. Nothing new until the weekly reset |

The weekly reset is a hard edge. In the last day before it, spend what is left on finished work, not on new starts.

## Cheap versus big

- Default: cheap contextless agents (Sonnet or Haiku) for analysis, ports, fixes, hater reviews. Big models only by exception and never at Yellow or Red.
- Most expensive and least valuable: re-reading large files, restarting contexts, repeated full-suite runs, and open-ended exploration. Avoid them at Yellow and Red.
- VICE and full-suite runs cost wall time, not tokens; they are fine at any tier but the model that watches them is not: poll with a plain shell loop or a background task, not a model wake.
- Fleet comms stay terse. Every wake and every long message costs tokens.

## Bursts

- Run work in bursts of about 3 hours inside a 5-hour window. Start a burst only if five_hour is under 50% (so the burst can finish) and the tier is Green or Yellow.
- Mark each burst: `tools/claude-quota mark "start: <what>" --tag swarm` and an end mark. The history then shows which jobs cost what.
- Between bursts the fleet is idle: no polling by a model. The systemd timer (no inference) keeps recording.
- Sizing a fan-out: estimate before launching. Number of agents times typical agent cost; if the estimate would take the projected weekly figure past the tier's limit, shrink or serialise it.

## Throttle rules

1. Check `tools/claude-quota status` (token-free) before every fan-out and at every checkpoint; run `now` only when the poller is stale.
2. If `will_cap_before_reset` is true for any bucket, step down one tier.
3. If a bucket's data is stale (poller down) or the burn is unknown, act as Yellow.
4. A step down is automatic. A step up needs two consecutive readings at least 15 minutes apart.
5. Any token-expired error (exit 2) means run a Claude Code command to refresh, then re-check; do not guess.

## Reporting

Each checkpoint message from the facilitator carries one line: tier, five_hour, seven_day, projected weekly at reset. The owner reads that line first.

## Open questions for the owner

- Is a weekly floor of 97% right, or should we keep a reserve (for example 5%) for owner-initiated work? 
- Do you want a Haiku-only mode at Red instead of full stop?
- Where should the history DB be backed up (it holds raw payloads; keep it private)?
