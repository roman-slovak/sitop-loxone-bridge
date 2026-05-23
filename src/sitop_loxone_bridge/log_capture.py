"""In-memory ring buffer of structlog events.

Bridge installs `capture_processor` into the structlog chain so every
emitted event lands in `LOG_BUFFER` as a plain dict (timestamp, level,
event, plus any kwargs the call site added). The bridge loop snapshots
the buffer into `runtime_state.json` each tick, which is how the web
dashboard pulls it.
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

DEFAULT_CAPACITY = 200


class LogBuffer:
    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = Lock()

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._buf.append(entry)

    def snapshot(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._buf)
        if limit is None or limit >= len(items):
            return items
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


LOG_BUFFER = LogBuffer()


def capture_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    # event_dict has been augmented by previous structlog processors
    # (timestamper, add_log_level, contextvars). We snapshot it before the
    # JSON renderer mutates it. dict() copy avoids the renderer's pop side
    # effects clobbering what we keep in memory.
    #
    # Skip routine successful ticks: in steady state they'd dominate the
    # buffer and push every interesting event (reconnects, errors, config
    # reloads) off the end. A tick that lost any Loxone write is still
    # captured because that's exactly the kind of thing we want to see.
    if (
        event_dict.get("event") == "tick"
        and event_dict.get("http_fail", 0) == 0
    ):
        return event_dict
    LOG_BUFFER.append(dict(event_dict))
    return event_dict
