# claude-quota: subscription quota for dispatchers

`tools/claude-quota` (stdlib-only Python) reads how much of the Claude subscription quota is used, records it, and projects the burn. The fleet that builds Breadbin can dispatch work by remaining quota.

It calls the **unofficial** OAuth usage endpoint that Claude Code's `/usage` uses. It may change or break without notice; `raw` prints the upstream payload to see what drifted, and the DB keeps every raw payload so history can be re-parsed. It uses the logged-in user's own token, read at call time (`CLAUDE_QUOTA_TOKEN`, else the Claude Code credentials file or the macOS keychain). The token is never stored or printed.

## Commands

- `now [--record] [--human]`: current utilization per bucket (`five_hour`, `seven_day`, per-model, `extra_usage`) with `remaining` and a `burn` block. Without `--record` it writes nothing and creates no DB; it reads history if a DB exists.
- `poll [--quiet]`: fetch and record. A new row only when values change; otherwise the last row's `last_seen` is extended. Failed polls are logged too.
- `history [--since 24h|7d|ISO] [--bucket B] [--format json|csv]`: usage rows and marks on one timeline.
- `mark "text" [--tag T]`: record a workload event.
- `raw`: the upstream payload.

Environment: `CLAUDE_QUOTA_DB` (default `~/.local/share/claude-quota/quota.db`), `CLAUDE_QUOTA_TOKEN`, `CLAUDE_CREDENTIALS`, `CLAUDE_QUOTA_BASE_URL` (tests point it at a local mock).

The DB holds raw payloads: keep it private and never commit it. It is created mode 0600 in a 0700 directory, and `*.db` is in `.gitignore`.

## Exit codes

0 ok; 2 auth (no token, expired, HTTP 401/403); 3 upstream or network error; 4 parse error (not JSON, no recognizable buckets). Errors are JSON on stderr.

## For a dispatcher

Run `tools/claude-quota now` and read `buckets.<name>.burn`. `will_cap_before_reset` is the throttle signal: true means the fitted rate reaches 100% before the window resets, so hold back new work. `hours_until_cap`, `projected_at_reset` and `remaining` give the margin. With under five minutes of history in the window, `burn` carries only a `note` and no rate; treat that as unknown, not safe. Windows are matched by `resets_at` within 120 s, since the reported time jitters.

Record continuously with cron:

```
*/5 * * * * tools/claude-quota poll --quiet
```

Mark sprints so the history shows which work cost what:

```
tools/claude-quota mark "start: <sprint>" --tag swarm
tools/claude-quota mark "stop: <sprint>" --tag swarm
```

Tests: `tools/test_claude_quota.py` (part of `make test-host`) runs against a local mock; nothing in the repo calls the live endpoint.
