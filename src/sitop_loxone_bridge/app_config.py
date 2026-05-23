"""Persistent runtime overlay on top of .env defaults.

The web UI lets the user edit OPC UA + Loxone connection details and the
poll interval without editing files on the host. Saved values land in
`<data_dir>/app_config.yaml` and shadow the env-based defaults from
`sitop_loxone_bridge.config.Settings`.

The original `Settings` object is still the source of truth for
non-editable knobs (web port, data_dir, log level), so we read it once at
startup and merge per-tick.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from sitop_loxone_bridge.config import Settings


class AppConfig(BaseModel):
    opcua_url: str
    opcua_username: str = ""
    opcua_password: str = ""
    opcua_session_timeout_ms: int = Field(default=120000, ge=1000)

    loxone_scheme: str = "http"
    loxone_host: str
    loxone_user: str
    loxone_pass: str
    loxone_verify_ssl: bool = True

    poll_interval_seconds: float = Field(default=5.0, gt=0)

    @field_validator("loxone_scheme")
    @classmethod
    def _scheme_valid(cls, v: str) -> str:
        if v not in {"http", "https"}:
            raise ValueError("loxone_scheme must be 'http' or 'https'")
        return v

    @classmethod
    def from_settings(cls, s: Settings) -> "AppConfig":
        return cls(
            opcua_url=s.opcua_url,
            opcua_username=s.opcua_username,
            opcua_password=s.opcua_password,
            opcua_session_timeout_ms=s.opcua_session_timeout_ms,
            loxone_scheme=s.loxone_scheme,
            loxone_host=s.loxone_host,
            loxone_user=s.loxone_user,
            loxone_pass=s.loxone_pass,
            loxone_verify_ssl=s.loxone_verify_ssl,
            poll_interval_seconds=s.poll_interval_seconds,
        )


def load_app_config(path: Path, fallback: Settings) -> AppConfig:
    """Read overlay if it exists, otherwise derive from .env-backed Settings."""
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return AppConfig.model_validate(raw)
        except Exception:
            # Corrupt YAML or schema mismatch — fall back to env defaults
            # rather than crashing on startup.
            pass
    return AppConfig.from_settings(fallback)


def save_app_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = cfg.model_dump(mode="json")
    data = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
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
