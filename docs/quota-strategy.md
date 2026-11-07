# Quota strategy

Draft for owner review. Inference quota is the binding constraint on the fleet. This page says how we spend it. Numbers come from `tools/claude-quota` (see `docs/claude-quota.md`); the owner's facts are marked as such.

## Facts

- Two buckets matter: `five_hour` (a rolling window) and `seven_day` (resets weekly). `now` and `status` report both, with a burn projection (`will_cap_before_reset`). `status` also reports the measured rate, the budget rate and a `suggested_tier`.
- Owner's facts: the weekly bucket stood near 75% at day start; work runs in bursts of about 3 hours inside the 5-hour windows; the fleet owns the product for the window.
- First live reading (2026-11-07 05:11 UTC): five_hour 44%, seven_day 86%, weekly reset 2026-11-09 05:00 UTC. About 14% of the week is left for roughly 48 hours. At the day's observed pace (about 11 points) that is tight: weekly, not the 5-hour window, is the constraint.
- The burn estimate needs about 5 minutes of history and is a straight-line fit. Treat "unknown" as "not safe".

## Tiers follow the burn rate

The tier is set by how fast we are consuming quota, not by how much is used. It moves as the rate moves. `tools/claude-quota status` (token-free, DB only) now reports the measured rate and a `suggested_tier`; the fleet reads that rather than working it out.

**Measured rate.** Per bucket, the net change in utilization over the trailing 1h, 6h and 24h, divided by the elapsed hours, in %/hour. The 1h rate is used when it exists, else 6h, else 24h (`rate.basis` says which). A reset inside the window cuts the window to the span since the reset. With fewer than two distinct readings, or under 10 minutes between them, the rate is unknown.

**Budget rate.** What the remaining budget allows: `(100 - utilization) / hours_to_reset`. The `ratio` is measured rate over budget rate.

| Tier | Ratio (worse of `seven_day` and `five_hour`) | Meaning |
|---|---|---|
| G | under 0.7 | Normal sprint: parallel lanes, hater reviews on kernel, bus and data-loss changes, full suite at milestones |
| Y | 0.7 to 1.0, or rate unknown | One lane at a time, cheaper models, reviews for correctness, data loss, kernel and bus only |
| R | 1.0 or more (projected to cap before reset) | Rate-limit the tasks: fewer parallel agents, cheaper models, longer gaps between wakes. Then resample `status` before deciding to do more |
| FLOOR | `seven_day` at 97% or more | Soft all-stop: finish and land what is in flight, start nothing new, hand to the owner |

Also forced:

- `five_hour` at 90% or more is R whatever the rate.
- A stale poller (no good poll in 15 minutes) is at least Y, whatever the numbers say.
- `utilization` at 100 is R (no budget left); a bucket whose reset time has passed is Y (the data is old).

Red means rate-limit tasks (fewer parallel agents, cheaper models, longer gaps) and resample status before deciding more. It does not mean stop; the rate usually falls within the hour once the fan-out is cut, and the tier follows it down.

The floor is the one absolute: 97% of the weekly bucket is a soft all-stop. Land what is finished and tested, hand to the owner, and wait for the owner or the weekly reset. `seven_day.rate.floor_headroom_pct` is the distance to it (`97 - utilization`).

**Hysteresis.** A step down (toward R) is immediate. A step up (toward G) needs the better tier to hold in two readings at least 15 minutes apart. `status` is stateless, so it computes the tier twice from the DB, as of now and as of 15 minutes ago, and `suggested_tier` is the worse of the two. `tier_now` and `tier_15m_ago` are reported for transparency. Corollary: after a weekly reset a FLOOR reading can be held for up to 15 minutes. If nothing existed 15 minutes ago, `tier_15m_ago` is null and `suggested_tier` is `tier_now`.

The weekly reset is a hard edge. In the last day before it, spend what is left on finished work, not on new starts; the budget rate climbs as the reset nears, which the ratio already reflects.

## Cheap versus big

- Default: cheap contextless agents (Sonnet or Haiku) for analysis, ports, fixes, hater reviews. Big models only by exception and never at Y or R.
- Most expensive and least valuable: re-reading large files, restarting contexts, repeated full-suite runs, and open-ended exploration. Avoid them at Y and R.
- VICE and full-suite runs cost wall time, not tokens; they are fine at any tier but the model that watches them is not: poll with a plain shell loop or a background task, not a model wake.
- Fleet comms stay terse. Every wake and every long message costs tokens.

## Bursts

- Run work in bursts of about 3 hours inside a 5-hour window. Start a burst only if five_hour is under 50% (so the burst can finish) and the tier is G or Y.
- Mark each burst: `tools/claude-quota mark "start: <what>" --tag swarm` and an end mark. The history then shows which jobs cost what.
- Between bursts the fleet is idle: no polling by a model. The systemd timer (no inference) keeps recording.
- Sizing a fan-out: estimate before launching. Number of agents times typical agent cost; if the estimate would push the burn rate past the budget rate (ratio 1.0), shrink or serialise it.

## Throttle rules

1. Check `tools/claude-quota status` (token-free) before every fan-out and at every checkpoint; run `now` only when the poller is stale. Act on `suggested_tier`.
2. At R, rate-limit tasks and resample `status` before deciding more. At FLOOR, soft all-stop and hand to the owner.
3. A stale poller or an unknown rate is Y; `status` already says so.
4. A step down is immediate. A step up needs two readings at least 15 minutes apart; `status` applies this itself.
5. Any token-expired error (exit 2) means run a Claude Code command to refresh, then re-check; do not guess.

## Reporting

Each checkpoint message from the facilitator carries one line: `suggested_tier`, five_hour, seven_day, and the seven_day rate against its budget rate. The owner reads that line first.

## Open questions for the owner

- Are the ratio cut-offs (0.7 and 1.0) and the five_hour 90% rule right? Is a weekly floor of 97% right, or should we keep a reserve (for example 5%) for owner-initiated work? 
- Do you want a Haiku-only mode at Red instead of full stop?
- Where should the history DB be backed up (it holds raw payloads; keep it private)?
