# claude-quota: subscription quota for dispatchers

`tools/claude-quota` (stdlib-only Python) reads how much of the Claude subscription quota is used, records it, and projects the burn. The fleet that builds Breadbin can dispatch work by remaining quota.

It calls the **unofficial** OAuth usage endpoint that Claude Code's `/usage` uses. It may change or break without notice; `raw` prints the upstream payload to see what drifted, and the DB keeps every raw payload so history can be re-parsed. It uses the logged-in user's own token, read at call time (`CLAUDE_QUOTA_TOKEN`, else the Claude Code credentials file or the macOS keychain). The token is never stored or printed.

## Commands

- `now [--record] [--human]`: current utilization per bucket (`five_hour`, `seven_day`, per-model, `extra_usage`) with `remaining` and a `burn` block. Without `--record` it writes nothing and creates no DB; it reads history if a DB exists.
- `poll [--quiet]`: fetch and record. A new row only when values change; otherwise the last row's `last_seen` is extended. Failed polls are logged too.
- `history [--since 24h|7d|ISO] [--bucket B] [--format json|csv]`: usage rows and marks on one timeline.
- `mark "text" [--tag T]`: record a workload event.
- `raw`: the upstream payload.
- `status [--json|--human] [--window-hours N]`: the token-free path (see below).

Environment: `CLAUDE_QUOTA_DB` (default `~/.local/share/claude-quota/quota.db`), `CLAUDE_QUOTA_TOKEN`, `CLAUDE_CREDENTIALS`, `CLAUDE_QUOTA_BASE_URL` (tests point it at a local mock).

The DB holds raw payloads: keep it private and never commit it. It is created mode 0600 in a 0700 directory, and `*.db` is in `.gitignore`.

## Exit codes

0 ok; 5 `status`: DB missing or empty; 6 `status`: stale; 2 auth (no token, expired, HTTP 401/403); 3 upstream or network error; 4 parse error (not JSON, no recognizable buckets). Errors are JSON on stderr.

## For a dispatcher

Run `tools/claude-quota now` and read `buckets.<name>.burn`. `will_cap_before_reset` is the throttle signal: true means the fitted rate reaches 100% before the window resets, so hold back new work. `hours_until_cap`, `projected_at_reset` and `remaining` give the margin. With under five minutes of history in the window, `burn` carries only a `note` and no rate; treat that as unknown, not safe. Windows are matched by `resets_at` within 120 s, since the reported time jitters.

### `status`: token-free

`tools/claude-quota status` reads only the history DB. It never touches the network, the token or the credentials, never creates or writes the DB, and costs no quota. The fleet reads this; one timer (below) polls. Output (JSON by default, `--human` for text):

- `buckets.<name>`: latest `utilization`, `remaining`, `resets_at` and the `burn` block (computed by the same code as `now`, against the latest recorded values with now = the current time).
- `last_poll_ok`, `last_poll_age_min`: the newest successful poll.
- `stale`: true when there is no successful poll in the last 15 minutes. Do not trust the numbers then.
- `recent_failures`: `count` of failed polls in the last hour, with `last_error` and `last_at`.
- `--window-hours N` adds `buckets.<name>.window`: `delta` is the net change in utilization over the last N hours (latest value minus the value at the cutoff; `partial` is true when history starts inside the window; `reset_in_window` is true when the quota window rolled over, so the delta is net and may be negative).

Exit 0 normally; 5 if the DB is missing or has no snapshots (a JSON error on stdout); 6 if stale (everything is still printed). Check the exit code before acting on the numbers.

### Polling with a systemd user timer

Tracking needs no model inference: a poll is one HTTP GET with the logged-in user's token. `tools/systemd/claude-quota.service` (oneshot, `claude-quota poll --quiet`) and `claude-quota.timer` (`OnBootSec=1min`, `OnUnitActiveSec=5min`, `Persistent=false`) are templates; the repo path appears as `@REPO@`, substituted at install time. Install them with:

```
tools/install-quota-timer.sh              # dry run: prints the units and the commands, changes nothing
tools/install-quota-timer.sh --yes        # copy to ~/.config/systemd/user, daemon-reload, enable --now
tools/install-quota-timer.sh --uninstall --yes
```

The script is POSIX sh and defaults to a dry run; nothing is written or run without `--yes`. `QUOTA_UNIT_DIR` overrides the unit directory. Poll failures are recorded in the `polls` table (and so show up in `status` as `recent_failures`); the unit itself also fails visibly in `systemctl --user status claude-quota`. Token expiry shows as exit 2 (`OAuth token expired`) until any Claude Code command refreshes the token; `status` then goes stale after 15 minutes. Run the installer from the long-lived clone, not a throwaway worktree: the units point at the checkout that ran it. Run the timer only on one machine per DB.

Record continuously with cron instead:

```
*/5 * * * * tools/claude-quota poll --quiet
```

Mark sprints so the history shows which work cost what:

```
tools/claude-quota mark "start: <sprint>" --tag swarm
tools/claude-quota mark "stop: <sprint>" --tag swarm
```

Tests: `tools/test_claude_quota.py` (part of `make test-host`) runs against a local mock; nothing in the repo calls the live endpoint.
