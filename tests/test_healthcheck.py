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
