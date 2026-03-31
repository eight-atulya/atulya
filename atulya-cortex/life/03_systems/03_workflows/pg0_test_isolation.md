# pg0 Test Isolation

## Trigger

Graph endpoint tests failed even though the graph logic was correct. The visible error was embedded PostgreSQL failing to bind `localhost:5556`.

## Root Cause

The test fixture in `atulya-api/tests/conftest.py` used a fixed pg0 port and a fixed pg0 instance name. That made local runs brittle in two ways:

1. a stale local pg0-backed postgres on `5556` blocked the suite
2. an override port could still reuse an older session's cached URL or collide with the same named pg0 instance

## Working Pattern

- Keep a stable default for normal test runs.
- Allow explicit test-time overrides through environment variables.
- Scope pg0 coordination files by both instance name and port.
- Derive a distinct pg0 instance name for non-default ports so parallel local sessions do not fight over the same embedded database identity.

## Commands

Run graph tests on the default fixture:

```bash
cd atulya-api && uv run pytest tests/test_graph_intelligence.py -q -n0
```

Run on an alternate isolated pg0 instance:

```bash
cd atulya-api && ATULYA_TEST_PG0_PORT=5567 uv run pytest tests/test_graph_intelligence.py -q -n0
```

Use `ATULYA_TEST_PG0_PORT=auto` when a fixed local port is likely to collide.

## Operator Notes

- If `lsof -nP -iTCP:5556 -sTCP:LISTEN` shows a postgres under `~/.pg0`, it is usually a stale embedded test instance, not production infrastructure.
- Prefer stopping it cleanly first with `pg_ctl ... stop`; if the listener persists, confirm the PID and terminate that exact stale process.
- If multiple local test sessions need isolation, do not reuse the same pg0 port override unless they are meant to share the same running instance.
