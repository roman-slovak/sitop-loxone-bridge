from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

SELECTION_VERSION = 1


class SelectedParameter(BaseModel):
    """One parameter the user has chosen to bridge into Loxone."""

    node_id: str
    path: str
    loxone_vi: str
    unit: str = ""
    dtype: str = "float"
    min: float | None = None
    max: float | None = None

    @field_validator("loxone_vi")
    @classmethod
    def _vi_name_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("loxone_vi must not be empty")
        # Loxone VI names accept letters, digits, underscore. No spaces or
        # slashes since they'd break the /dev/sps/io/<name>/<value> URL path.
        if any(c in v for c in " /?#&"):
            raise ValueError(f"loxone_vi contains forbidden character: {v!r}")
        return v


class Selection(BaseModel):
    version: int = SELECTION_VERSION
    opcua_url: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parameters: list[SelectedParameter] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _version_supported(cls, v: int) -> int:
        if v != SELECTION_VERSION:
            raise ValueError(
                f"unsupported selection version {v}, expected {SELECTION_VERSION}"
            )
        return v

    @field_validator("parameters")
    @classmethod
    def _vi_names_unique(
        cls, params: list[SelectedParameter]
    ) -> list[SelectedParameter]:
        seen: set[str] = set()
        for p in params:
            if p.loxone_vi in seen:
                raise ValueError(f"duplicate loxone_vi: {p.loxone_vi}")
            seen.add(p.loxone_vi)
        return params


def load_selection(path: Path) -> Selection | None:
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return None
    return Selection.model_validate(raw)


def save_selection(path: Path, selection: Selection) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = selection.model_dump(mode="json")
    data = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    _atomic_write_text(path, data)


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
