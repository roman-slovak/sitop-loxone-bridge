# Healthcheck endpoint + Docker HEALTHCHECK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative healthcheck that lets Docker restart the bridge only when truly frozen, and exposes a `/healthz` HTTP endpoint on the web service for external monitors.

**Architecture:** One pure function `compute_health(state_path, fresh_window_s, now=None)` returns a `BridgeHealth` dataclass. The bridge container's Docker HEALTHCHECK invokes `python -m sitop_loxone_bridge.healthcheck` which calls that function and exits 0/1. The web service registers a new `health_router` (no prefix) whose `GET /healthz` calls the same function and returns 200/503 + JSON.

**Tech Stack:** Python 3.13, pydantic, pydantic-settings, FastAPI, asyncua-based existing runtime, pytest, Docker Compose healthchecks.

**Spec:** `docs/superpowers/specs/2026-05-24-healthcheck-design.md`

---

## File map

| File | Why |
|---|---|
| `src/sitop_loxone_bridge/config.py` | Add `health_fresh_window_s` Settings field |
| `src/sitop_loxone_bridge/healthcheck.py` (new) | `BridgeHealth`, `compute_health`, CLI entrypoint |
| `src/sitop_loxone_bridge/web/api.py` | Register `health_router` with `GET /healthz` |
| `src/sitop_loxone_bridge/web/app.py` | Include `health_router` (no prefix) |
| `docker-compose.yml` | Add `healthcheck:` block on both services |
| `.env.example` | Document `HEALTH_FRESH_WINDOW_S` |
| `README.md` | Healthcheck section |
| `tests/test_healthcheck.py` (new) | Pure-function unit tests for `compute_health` |
| `tests/test_web_api.py` | Add `/healthz` integration tests |

---

### Task 1: Add `health_fresh_window_s` to Settings

**Files:**
- Modify: `src/sitop_loxone_bridge/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (after the existing tests):

```python
def test_health_fresh_window_default(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    settings = Settings()
    assert settings.health_fresh_window_s == 60.0


def test_health_fresh_window_override(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("HEALTH_FRESH_WINDOW_S", "30")
    settings = Settings()
    assert settings.health_fresh_window_s == 30.0


def test_health_fresh_window_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("HEALTH_FRESH_WINDOW_S", "0")
    with pytest.raises(ValueError):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_health_fresh_window_default -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'health_fresh_window_s'`.

- [ ] **Step 3: Add the field to `Settings`**

In `src/sitop_loxone_bridge/config.py`, locate the `--- Bridge runtime ---` block and add `health_fresh_window_s` immediately after `poll_interval_seconds`:

```python
    # --- Bridge runtime ---
    poll_interval_seconds: float = Field(default=5.0, gt=0)
    log_level: str = "INFO"
    health_fresh_window_s: float = Field(default=60.0, gt=0)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: all three new tests pass; pre-existing config tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/sitop_loxone_bridge/config.py tests/test_config.py
git commit -m "Add health_fresh_window_s setting (default 60s)"
```

---

### Task 2: `healthcheck.py` — `BridgeHealth` + `compute_health` + CLI

**Files:**
- Create: `src/sitop_loxone_bridge/healthcheck.py`
- Create: `tests/test_healthcheck.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_healthcheck.py`:

```python
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sitop_loxone_bridge.healthcheck import BridgeHealth, compute_health
from sitop_loxone_bridge.runtime_state import RuntimeState, save_state


FIXED_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


def _write_state(path: Path, tick: datetime | None) -> None:
    state = RuntimeState(last_tick=tick, opcua_connected=True)
    save_state(path, state)


def test_fresh_tick_is_healthy(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_state(path, FIXED_NOW - timedelta(seconds=5))
    result = compute_health(path, fresh_window_s=60.0, now=FIXED_NOW)
    assert result.ok is True
    assert result.last_tick_age_s == pytest.approx(5.0)
    assert result.fresh_window_s == 60.0


def test_stale_tick_is_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_state(path, FIXED_NOW - timedelta(seconds=120))
    result = compute_health(path, fresh_window_s=60.0, now=FIXED_NOW)
    assert result.ok is False
    assert result.last_tick_age_s == pytest.approx(120.0)


def test_boundary_at_window_is_unhealthy(tmp_path: Path) -> None:
    """Boundary uses strict `<`, not `<=`."""
    path = tmp_path / "state.json"
    _write_state(path, FIXED_NOW - timedelta(seconds=60))
    result = compute_health(path, fresh_window_s=60.0, now=FIXED_NOW)
    assert result.ok is False


def test_missing_file_is_unhealthy(tmp_path: Path) -> None:
    result = compute_health(
        tmp_path / "missing.json", fresh_window_s=60.0, now=FIXED_NOW
    )
    assert result.ok is False
    assert result.last_tick is None
    assert result.last_tick_age_s is None


def test_state_without_tick_is_unhealthy(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_state(path, None)
    result = compute_health(path, fresh_window_s=60.0, now=FIXED_NOW)
    assert result.ok is False
    assert result.last_tick is None
    assert result.last_tick_age_s is None


def test_now_defaults_to_utc(tmp_path: Path) -> None:
    """If `now` is omitted, the function uses datetime.now(UTC)."""
    path = tmp_path / "state.json"
    _write_state(path, datetime.now(UTC))
    result = compute_health(path, fresh_window_s=60.0)
    assert result.ok is True
    assert result.last_tick_age_s is not None
    assert result.last_tick_age_s < 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_healthcheck.py -v`
Expected: every test FAILs with `ModuleNotFoundError: No module named 'sitop_loxone_bridge.healthcheck'`.

- [ ] **Step 3: Implement the module**

Create `src/sitop_loxone_bridge/healthcheck.py`:

```python
"""Liveness check for the bridge tick loop.

Pure function `compute_health` reads `runtime_state.json` and answers a
single question: is the bridge ticking? Bridge container's Docker
HEALTHCHECK runs this module's __main__ and exits 0/1; the web
service's GET /healthz endpoint calls the same function and renders
JSON.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sitop_loxone_bridge.runtime_state import load_state


@dataclass(frozen=True)
class BridgeHealth:
    ok: bool
    last_tick: datetime | None
    last_tick_age_s: float | None
    fresh_window_s: float


def compute_health(
    state_path: Path,
    fresh_window_s: float,
    now: datetime | None = None,
) -> BridgeHealth:
    now = now if now is not None else datetime.now(UTC)

    # load_state returns a default RuntimeState if the file is missing or
    # corrupt. Either way last_tick will be None, which we treat as unhealthy.
    state = load_state(state_path)
    last_tick = state.last_tick
    if last_tick is None:
        return BridgeHealth(
            ok=False,
            last_tick=None,
            last_tick_age_s=None,
            fresh_window_s=fresh_window_s,
        )

    age = (now - last_tick).total_seconds()
    return BridgeHealth(
        ok=age < fresh_window_s,
        last_tick=last_tick,
        last_tick_age_s=age,
        fresh_window_s=fresh_window_s,
    )


def main() -> int:
    """CLI entrypoint used by the bridge container's Docker HEALTHCHECK."""
    from sitop_loxone_bridge.config import Settings

    settings = Settings()
    health = compute_health(
        settings.state_path, fresh_window_s=settings.health_fresh_window_s
    )
    return 0 if health.ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_healthcheck.py -v`
Expected: all six tests pass.

- [ ] **Step 5: Smoke-test the CLI**

Run: `LOXONE_HOST=x LOXONE_USER=x LOXONE_PASS=x DATA_DIR=/tmp/sitop-hc-smoketest mkdir -p /tmp/sitop-hc-smoketest && LOXONE_HOST=x LOXONE_USER=x LOXONE_PASS=x DATA_DIR=/tmp/sitop-hc-smoketest uv run python -m sitop_loxone_bridge.healthcheck; echo "exit=$?"`
Expected: `exit=1` (no `runtime_state.json` in fresh dir → unhealthy).

- [ ] **Step 6: Commit**

```bash
git add src/sitop_loxone_bridge/healthcheck.py tests/test_healthcheck.py
git commit -m "Add healthcheck module: pure compute_health + CLI"
```

---

### Task 3: Web `/healthz` route

**Files:**
- Modify: `src/sitop_loxone_bridge/web/api.py`
- Modify: `src/sitop_loxone_bridge/web/app.py`
- Modify: `tests/test_web_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_api.py`:

```python
from datetime import UTC, datetime, timedelta

from sitop_loxone_bridge.runtime_state import RuntimeState, save_state


@pytest.mark.asyncio
async def test_healthz_returns_200_when_tick_is_fresh(app_with_tmp_dir) -> None:
    app, settings = app_with_tmp_dir
    save_state(
        settings.state_path,
        RuntimeState(
            last_tick=datetime.now(UTC) - timedelta(seconds=5),
            opcua_connected=True,
        ),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["bridge_ok"] is True
        assert body["web_ok"] is True
        assert body["last_tick_age_s"] < 60
        assert body["fresh_window_s"] == 60.0


@pytest.mark.asyncio
async def test_healthz_returns_503_when_tick_is_stale(app_with_tmp_dir) -> None:
    app, settings = app_with_tmp_dir
    save_state(
        settings.state_path,
        RuntimeState(
            last_tick=datetime.now(UTC) - timedelta(seconds=300),
            opcua_connected=False,
        ),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/healthz")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["bridge_ok"] is False


@pytest.mark.asyncio
async def test_healthz_returns_503_when_no_state(app_with_tmp_dir) -> None:
    app, _settings = app_with_tmp_dir
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/healthz")
        assert r.status_code == 503
        body = r.json()
        assert body["bridge_ok"] is False
        assert body["last_tick"] is None
        assert body["last_tick_age_s"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_api.py -v -k healthz`
Expected: three FAILs with 404 (`/healthz` route does not exist yet).

- [ ] **Step 3: Add the `health_router` to `web/api.py`**

In `src/sitop_loxone_bridge/web/api.py`, add the import and the new router at the top of the existing imports:

```python
from fastapi.responses import JSONResponse

from sitop_loxone_bridge.healthcheck import compute_health
```

Then, immediately after the existing `router = APIRouter()` line, add:

```python
# Registered at the app root in create_app() so the path is /healthz (no /api prefix).
health_router = APIRouter()


@health_router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    settings = _settings(request)
    health = compute_health(
        settings.state_path,
        fresh_window_s=settings.health_fresh_window_s,
    )
    body = {
        "status": "ok" if health.ok else "degraded",
        "web_ok": True,
        "bridge_ok": health.ok,
        "last_tick": health.last_tick.isoformat() if health.last_tick else None,
        "last_tick_age_s": (
            round(health.last_tick_age_s, 2)
            if health.last_tick_age_s is not None
            else None
        ),
        "fresh_window_s": health.fresh_window_s,
    }
    return JSONResponse(body, status_code=200 if health.ok else 503)
```

- [ ] **Step 4: Mount `health_router` in `create_app()`**

In `src/sitop_loxone_bridge/web/app.py`, locate the existing block:

```python
    from sitop_loxone_bridge.web import api, pages

    app.include_router(pages.router)
    app.include_router(api.router, prefix="/api")
    return app
```

Replace with:

```python
    from sitop_loxone_bridge.web import api, pages

    app.include_router(pages.router)
    app.include_router(api.health_router)        # /healthz at root
    app.include_router(api.router, prefix="/api")
    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web_api.py -v -k healthz`
Expected: all three new tests pass.

Run: `uv run pytest -q`
Expected: full suite green (39+ tests).

- [ ] **Step 6: Commit**

```bash
git add src/sitop_loxone_bridge/web/api.py src/sitop_loxone_bridge/web/app.py tests/test_web_api.py
git commit -m "Web: GET /healthz reports bridge tick freshness"
```

---

### Task 4: Docker HEALTHCHECK on both services

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add `healthcheck` to `sitop-bridge`**

In `docker-compose.yml`, in the `sitop-bridge` service block (between `volumes:` and `logging:`), add:

```yaml
    healthcheck:
      test: ["CMD", "python", "-m", "sitop_loxone_bridge.healthcheck"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 60s
```

- [ ] **Step 2: Add `healthcheck` to `sitop-web`**

In the `sitop-web` service block (between `depends_on:` and `logging:`), add:

```yaml
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

- [ ] **Step 3: Validate compose syntax**

Run: `docker compose config -q`
Expected: no output (silent success). Any YAML/schema error would be printed.

- [ ] **Step 4: Rebuild + start**

Run: `docker compose up -d --build`
Expected: both containers start.

- [ ] **Step 5: Wait for first healthcheck pass, then verify**

Run: `sleep 75 && docker inspect sitop-bridge --format '{{.State.Health.Status}}' && docker inspect sitop-web --format '{{.State.Health.Status}}'`
Expected:
```
healthy
healthy
```

Then: `curl -i http://localhost:8767/healthz`
Expected: `HTTP/1.1 200 OK` and JSON body with `"bridge_ok": true`.

- [ ] **Step 6: Simulate freeze (optional but recommended)**

Run: `docker pause sitop-bridge && sleep 70 && docker inspect sitop-bridge --format '{{.State.Health.Status}}'`
Expected: `unhealthy`.

Recovery: `docker unpause sitop-bridge && sleep 25 && docker inspect sitop-bridge --format '{{.State.Health.Status}}'`
Expected: back to `healthy`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "Docker compose: HEALTHCHECK for sitop-bridge and sitop-web"
```

---

### Task 5: Docs

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Document the env var in `.env.example`**

In `.env.example`, locate the `# --- Bridge runtime ---` block and add a line after `LOG_LEVEL=INFO`:

```
# Bridge is reported unhealthy if last_tick is older than this many seconds.
# Conservative default (60 s) tolerates OPC UA reconnect backoff (max ~60 s).
HEALTH_FRESH_WINDOW_S=60
```

- [ ] **Step 2: Add a Healthcheck section to README.md**

Append to `README.md`, just before the final `## Local development` section:

```markdown
## Healthcheck

Both containers expose Docker HEALTHCHECKs:

- `sitop-bridge` runs `python -m sitop_loxone_bridge.healthcheck`, which
  reads `runtime_state.json` and exits 0 if `last_tick` is within
  `HEALTH_FRESH_WINDOW_S` seconds (default 60 s), else 1.
- `sitop-web` curls `GET /healthz` locally and propagates the status.

External monitors can hit `http://<host>:8767/healthz` to get a JSON
body describing the bridge's freshness:

```json
{
  "status": "ok",
  "web_ok": true,
  "bridge_ok": true,
  "last_tick": "2026-05-24T10:30:00+00:00",
  "last_tick_age_s": 4.2,
  "fresh_window_s": 60
}
```

`HTTP 200` when `bridge_ok` is true, `503` otherwise. Web stays healthy
independently of the bridge — if you see `200` from `/` but `503` from
`/healthz`, the web is fine and the bridge is stuck.
```

(Keep the existing fenced code block delimiter for the surrounding doc
intact.)

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "Docs: HEALTH_FRESH_WINDOW_S env var + healthcheck section"
```

---

### Task 6: Push

- [ ] **Step 1: Run the full suite one more time**

Run: `uv run pytest -q`
Expected: all tests green (≈ 41 tests).

- [ ] **Step 2: Push**

Run: `git push`
Expected: GitHub Actions builds and publishes a new multi-arch image to `ghcr.io/roman-slovak/sitop-loxone-bridge:latest` (tracked separately; no action needed beyond push).

---

## Self-review summary

- **Spec coverage:** every spec section mapped to a task — Settings field (Task 1), `compute_health` + CLI (Task 2), `/healthz` route (Task 3), Docker HEALTHCHECK on both services (Task 4), env doc + README (Task 5), push to trigger image build (Task 6).
- **Boundary case** (`age == fresh_window_s` is unhealthy) covered by `test_boundary_at_window_is_unhealthy`.
- **OPC UA reconnect tolerance** is implicit in the 60 s default — verified by Task 4 Step 6 (`docker pause` for 70 s).
- **Types consistent:** `BridgeHealth` fields used in Task 2 match those rendered in Task 3 (`status`, `web_ok`, `bridge_ok`, `last_tick`, `last_tick_age_s`, `fresh_window_s`). The `compute_health` signature `(state_path, fresh_window_s, now=None)` is identical in both the module and its callers.
- **No placeholders:** every step shows the exact code/command to run.
