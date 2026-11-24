# claude-quota: ask for the current quota

`tools/claude-quota now [--human]` is an ad hoc query: it prints how much of the Claude subscription quota is used, per bucket (`five_hour`, `seven_day`, per-model, `extra_usage`) with `remaining` and the reset time. `raw` prints the upstream payload. Agents may run it to see live data; nothing polls, schedules or dispatches on it (agent management is manual).

It calls the **unofficial** OAuth usage endpoint that Claude Code's `/usage` uses, so it may break without notice; `raw` shows what drifted. It uses the logged-in user's own token, read at call time (`CLAUDE_QUOTA_TOKEN`, else the Claude Code credentials file or the macOS keychain), and never stores or prints it.

Exit codes: 0 ok; 2 auth (no token, expired, HTTP 401/403); 3 upstream or network error; 4 parse error. Errors are JSON on stderr. Tests: `tools/test_claude_quota.py` (in `make test-host`), against a local mock.

The tool still carries the old recording subcommands (`poll`, `status`, `history`, `mark`) and a history DB; they are unused and slated for removal (see `docs/wip.md`).
