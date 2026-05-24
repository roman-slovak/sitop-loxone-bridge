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
