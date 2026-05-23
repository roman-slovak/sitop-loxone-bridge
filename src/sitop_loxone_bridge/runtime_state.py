from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ParameterState(BaseModel):
    loxone_vi: str
    path: str = ""
    unit: str = ""
    value: float | None = None
    last_loxone_status: int | None = None
    consecutive_loxone_failures: int = 0


class RuntimeState(BaseModel):
    last_tick: datetime | None = None
    opcua_connected: bool = False
    opcua_url: str = ""
    ticks_total: int = 0
    ticks_failed: int = 0
    selection_mtime: datetime | None = None
    selection_count: int = 0
    last_error: str | None = None
    parameters: list[ParameterState] = Field(default_factory=list)

    def with_tick_success(self, params: list[ParameterState]) -> "RuntimeState":
        return self.model_copy(
            update={
                "last_tick": datetime.now(UTC),
                "opcua_connected": True,
                "ticks_total": self.ticks_total + 1,
                "parameters": params,
                "last_error": None,
            }
        )

    def with_tick_failure(self, err: str) -> "RuntimeState":
        return self.model_copy(
            update={
                "last_tick": datetime.now(UTC),
                "ticks_total": self.ticks_total + 1,
                "ticks_failed": self.ticks_failed + 1,
                "last_error": err,
            }
        )


def load_state(path: Path) -> RuntimeState:
    if not path.exists():
        return RuntimeState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return RuntimeState.model_validate(raw)
    except (json.JSONDecodeError, ValueError):
        # Corrupt or older schema — start fresh rather than crashing the web UI.
        return RuntimeState()


def save_state(path: Path, state: RuntimeState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump(mode="json")
    data = json.dumps(payload, indent=2)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
