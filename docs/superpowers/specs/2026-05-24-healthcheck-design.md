# Healthcheck endpoint + Docker HEALTHCHECK

## Context

The bridge and web service today have no explicit liveness signal. If the
bridge process freezes (deadlock, unhandled exception in an obscure code
path) the Docker container keeps reporting `Up` and nothing restarts it.
Externally we also can't tell whether the bridge is currently writing to
Loxone — we'd have to `docker logs` or read the dashboard.

Goal: add a conservative healthcheck that lets Docker restart the bridge
when it has truly stopped, and lets external monitoring (uptime-kuma,
Grafana synthetic, simple cron) verify the system end-to-end with one
HTTP GET.

## Design

### Source of truth: bridge tick freshness

`runtime_state.json` already records `last_tick` after every poll. The
healthcheck reduces to: is `now − last_tick < fresh_window_s`?

`fresh_window_s` defaults to **60 s**. At a 5 s poll interval that
tolerates 12 missed ticks — well past the worst-case OPC UA reconnect
backoff (max 64 s capped at 60 s, but in practice 8–16 s after a
transient failure). Anything longer is genuinely stuck.

Configurable via env var `HEALTH_FRESH_WINDOW_S` (pydantic-settings
field on `Settings`) for the rare case a user runs a longer
`POLL_INTERVAL_SECONDS`.

### Shared computation: `healthcheck.py`

```
src/sitop_loxone_bridge/healthcheck.py
  ├── BridgeHealth dataclass: ok, last_tick, last_tick_age_s, fresh_window_s
  ├── compute_health(state_path, fresh_window_s, now=None) -> BridgeHealth
  │     pure function: reads json, returns dataclass; no side effects
  └── __main__: exit 0 if compute_health(...).ok else 1
                (so Docker's bridge HEALTHCHECK CMD can call it directly)
```

`compute_health` handles three cases:
- `runtime_state.json` missing → `ok=False`, `last_tick=None`, `last_tick_age_s=None`
- `runtime_state.json` exists but `last_tick` is None (no tick yet) → `ok=False`, age=None
- `last_tick` present → `ok = age < fresh_window_s`

The `now` parameter is dependency-injected for deterministic tests.

### Bridge container HEALTHCHECK

`docker-compose.yml`:

```yaml
sitop-bridge:
  healthcheck:
    test: ["CMD", "python", "-m", "sitop_loxone_bridge.healthcheck"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 60s
```

15 s × 3 retries ≈ 45 s of consecutive failures before Docker flips the
container to `unhealthy`. `start_period` 60 s gives the bridge time to
boot, connect to OPC UA and run its first tick before the check matters.

Bridge container has no HTTP server today and won't grow one for this —
the in-process `python -m` call is cheap and uses the same code path the
web endpoint uses.

### Web container `/healthz` endpoint

New route registered on the FastAPI app **outside** the `/api` prefix
so it sits at `http://host:8767/healthz` (where external tools look by
convention). Concretely: a separate `health_router` defined in
`web/api.py` and included in `create_app()` with no prefix, alongside
the existing `pages.router` (no prefix) and `api.router` (`/api`
prefix):

```python
@router.get("/healthz")
async def healthz(request: Request) -> Response:
    settings = _settings(request)
    health = compute_health(settings.state_path, settings.health_fresh_window_s)
    body = {
        "status": "ok" if health.ok else "degraded",
        "web_ok": True,
        "bridge_ok": health.ok,
        "last_tick": health.last_tick.isoformat() if health.last_tick else None,
        "last_tick_age_s": round(health.last_tick_age_s, 2) if health.last_tick_age_s is not None else None,
        "fresh_window_s": health.fresh_window_s,
    }
    return JSONResponse(body, status_code=200 if health.ok else 503)
```

`web_ok` is always `true` — if the web process were down the request
wouldn't reach us. We keep the key in the body for symmetry with how
external monitors typically render two-state cards.

`docker-compose.yml`:

```yaml
sitop-web:
  healthcheck:
    test:
      - "CMD"
      - "python"
      - "-c"
      - "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8767/healthz',timeout=3).status==200 else 1)"
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 30s
```

`python -c` rather than `curl` because the slim image doesn't ship curl
and adding it just for healthcheck would bloat the layer.

## Failure semantics

| Scenario                                  | Bridge container | Web container | Notes                                  |
| ----------------------------------------- | ---------------- | ------------- | -------------------------------------- |
| Cold start, no tick yet                   | unhealthy        | unhealthy     | Covered by `start_period`              |
| Steady-state ticking                      | healthy          | healthy       | —                                      |
| OPC UA transient outage (10–30 s)         | healthy          | healthy       | Recovers within fresh window           |
| OPC UA outage > 60 s                      | unhealthy        | unhealthy     | Real failure — Docker restarts bridge  |
| Selection empty (idle state)              | healthy          | healthy       | Bridge ticks the state file at idle    |
| Loxone offline, OPC UA fine               | healthy          | healthy       | Bridge is doing its job; degraded view via dashboard |
| Web process hung                          | healthy          | unhealthy     | Independent containers, independent checks |
| Bridge process frozen (deadlock)          | unhealthy        | unhealthy     | last_tick goes stale                   |
| `runtime_state.json` missing/corrupt      | unhealthy        | unhealthy     | `load_state` returns defaults with `last_tick=None` |

Important nuance: when **OPC UA** is offline the bridge **still writes**
`runtime_state.json` (the failure-path code in `bridge.py` calls
`_persist_state` to record `last_error` and increment `ticks_failed`).
That keeps `last_tick` fresh during transient failures and avoids spurious
restarts. Only if the *whole tick loop* stops calling `_persist_state` —
i.e. the process is genuinely frozen — does the freshness check fail.

## Data flow

```
bridge: every tick      → writes runtime_state.json (last_tick = now)
bridge: HEALTHCHECK CMD → reads same file, exit 0/1
web:    GET /healthz    → reads same file, returns 200/503 + JSON
docker: every 15 s      → invokes both healthchecks independently
```

No new state files. No coupling between the two containers beyond the
shared `/data` volume that already exists.

## Configuration

New env var on `Settings` (pydantic-settings):

```
HEALTH_FRESH_WINDOW_S=60     # seconds; default 60
```

Documented in `.env.example`. Not exposed in the web Connection settings
form — operations-tier knob, not a runtime choice.

## Tests

- `tests/test_healthcheck.py` — pure function:
  - fresh tick → ok
  - stale tick → not ok
  - missing file → not ok
  - last_tick is None → not ok
  - boundary: age exactly at fresh_window_s → not ok (`<`, not `≤`)
  - `compute_health(now=fixed_datetime)` for deterministic age math
- `tests/test_web_api.py` — extend:
  - `/healthz` with fresh state → 200, body shape
  - `/healthz` with stale state → 503

## Out of scope (deliberate)

- Bridge does **not** add its own HTTP server. Healthcheck stays a CLI.
- No `/readyz` split (we are not on k8s).
- No per-parameter health (Loxone write failures already surface on the
  dashboard with `last_loxone_status` and `consecutive_loxone_failures`).
- No restart policy changes. Existing `restart: unless-stopped` plus the
  new healthcheck is enough; auto-restart on `unhealthy` would need
  `autoheal` sidecar or compose v3.10+ `restart: on-failure` semantics,
  which the user can add later if they want.

## Verification

1. `uv run pytest` — new and existing tests green.
2. `docker compose up -d --build`
3. `docker inspect sitop-bridge --format '{{json .State.Health}}'` shows
   `Status: starting` initially, then `healthy` after first tick.
4. `curl -i http://localhost:8767/healthz` → `200`, JSON with
   `bridge_ok: true`.
5. Simulate freeze: `docker pause sitop-bridge`, wait 60 s, then
   `docker inspect` reports `Status: unhealthy` and `curl /healthz`
   returns `503` with `bridge_ok: false`.
6. `docker unpause sitop-bridge` — recovers within one poll interval +
   one healthcheck interval (~20 s).
