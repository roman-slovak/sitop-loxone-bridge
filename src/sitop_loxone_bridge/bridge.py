from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

from sitop_loxone_bridge.app_config import AppConfig, load_app_config
from sitop_loxone_bridge.config import Settings
from sitop_loxone_bridge.loxone_writer import LoxoneTarget, LoxoneWriter, WriteOutcome
from sitop_loxone_bridge.opcua_reader import OpcuaReader, ReadResult
from sitop_loxone_bridge.runtime_state import (
    ParameterState,
    RuntimeState,
    load_state,
    save_state,
)
from sitop_loxone_bridge.selection import Selection, load_selection

log = structlog.get_logger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    for noisy in ("asyncua", "opcua", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def _build_writer(cfg: AppConfig) -> LoxoneWriter:
    return LoxoneWriter(
        target=LoxoneTarget(
            scheme=cfg.loxone_scheme,
            host=cfg.loxone_host,
            user=cfg.loxone_user,
            password=cfg.loxone_pass,
            verify_ssl=cfg.loxone_verify_ssl,
        )
    )


async def _run(settings: Settings, once: bool) -> int:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    cfg = load_app_config(settings.app_config_path, fallback=settings)
    app_cfg_mtime = _mtime(settings.app_config_path)

    state = load_state(settings.state_path)
    state = state.model_copy(update={"opcua_url": cfg.opcua_url})
    save_state(settings.state_path, state)

    writer = _build_writer(cfg)
    reader: OpcuaReader | None = None
    failure_streak: dict[str, int] = {}
    selection_mtime: float | None = None
    selection: Selection | None = None
    consecutive_opcua_errors = 0

    try:
        while not stop_event.is_set():
            # 1. Hot-reload app_config (connection details) on mtime change.
            new_app_mtime = _mtime(settings.app_config_path)
            if new_app_mtime != app_cfg_mtime:
                app_cfg_mtime = new_app_mtime
                new_cfg = load_app_config(settings.app_config_path, fallback=settings)
                if (
                    new_cfg.opcua_url != cfg.opcua_url
                    or new_cfg.opcua_username != cfg.opcua_username
                    or new_cfg.opcua_password != cfg.opcua_password
                ):
                    if reader is not None:
                        await reader.disconnect()
                        reader = None
                if (
                    new_cfg.loxone_scheme != cfg.loxone_scheme
                    or new_cfg.loxone_host != cfg.loxone_host
                    or new_cfg.loxone_user != cfg.loxone_user
                    or new_cfg.loxone_pass != cfg.loxone_pass
                    or new_cfg.loxone_verify_ssl != cfg.loxone_verify_ssl
                ):
                    await writer.aclose()
                    writer = _build_writer(new_cfg)
                cfg = new_cfg
                state = state.model_copy(update={"opcua_url": cfg.opcua_url})
                log.info(
                    "app_config.reloaded",
                    opcua_url=cfg.opcua_url,
                    loxone_host=cfg.loxone_host,
                )

            # 2. Hot-reload selection.
            new_mtime = _mtime(settings.selection_path)
            if new_mtime != selection_mtime:
                selection_mtime = new_mtime
                old_selection = selection
                selection = (
                    load_selection(settings.selection_path)
                    if new_mtime is not None
                    else None
                )
                if reader is not None:
                    await reader.disconnect()
                    reader = None
                failure_streak = {}
                if selection is None or not selection.parameters:
                    log.warning(
                        "selection.empty",
                        path=str(settings.selection_path),
                    )
                else:
                    log.info(
                        "selection.loaded",
                        parameters=len(selection.parameters),
                        changed=old_selection is not None,
                    )

            # 3. If no selection, idle.
            if selection is None or not selection.parameters:
                state = state.model_copy(
                    update={
                        "opcua_connected": False,
                        "selection_count": 0,
                        "parameters": [],
                        "selection_mtime": (
                            datetime.fromtimestamp(selection_mtime, tz=UTC)
                            if selection_mtime
                            else None
                        ),
                    }
                )
                save_state(settings.state_path, state)
                if once:
                    return 0
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=cfg.poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
                continue

            # 4. Ensure OPC UA connected.
            if reader is None:
                reader = OpcuaReader(
                    url=cfg.opcua_url,
                    parameters=selection.parameters,
                    username=cfg.opcua_username,
                    password=cfg.opcua_password,
                    session_timeout_ms=cfg.opcua_session_timeout_ms,
                )
                try:
                    await reader.connect()
                    consecutive_opcua_errors = 0
                except Exception as exc:
                    consecutive_opcua_errors += 1
                    log.error("opcua.connect_failed", error=str(exc))
                    state = state.with_tick_failure(f"connect: {exc}")
                    state = state.model_copy(update={"opcua_connected": False})
                    save_state(settings.state_path, state)
                    reader = None
                    backoff = min(60.0, 2 ** min(consecutive_opcua_errors, 6))
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                    except asyncio.TimeoutError:
                        pass
                    continue

            # 5. Read + write.
            try:
                readings = await reader.read()
            except Exception as exc:
                consecutive_opcua_errors += 1
                log.error("opcua.read_failed", error=str(exc))
                state = state.with_tick_failure(f"read: {exc}")
                state = state.model_copy(update={"opcua_connected": False})
                save_state(settings.state_path, state)
                if reader is not None:
                    try:
                        await reader.disconnect()
                    except Exception:
                        pass
                    reader = None
                if once:
                    return 1
                backoff = min(60.0, 2 ** min(consecutive_opcua_errors, 6))
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                continue

            consecutive_opcua_errors = 0
            outcomes = await writer.send_many(
                [(r.loxone_vi, r.value) for r in readings if r.value is not None]
            )
            outcome_by_vi = {o.vi_name: o for o in outcomes}

            param_states = _build_parameter_states(
                readings, outcome_by_vi, failure_streak
            )
            state = state.with_tick_success(param_states)
            state = state.model_copy(
                update={
                    "selection_count": len(selection.parameters),
                    "selection_mtime": (
                        datetime.fromtimestamp(selection_mtime, tz=UTC)
                        if selection_mtime
                        else None
                    ),
                }
            )
            save_state(settings.state_path, state)
            log.info(
                "tick",
                parameters=len(readings),
                http_ok=sum(1 for o in outcomes if o.ok),
                http_fail=sum(1 for o in outcomes if not o.ok),
            )

            if once:
                return 0

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=cfg.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
    finally:
        if reader is not None:
            try:
                await reader.disconnect()
            except Exception:
                pass
        await writer.aclose()

    return 0


def _build_parameter_states(
    readings: list[ReadResult],
    outcomes: dict[str, WriteOutcome],
    failure_streak: dict[str, int],
) -> list[ParameterState]:
    states: list[ParameterState] = []
    for r in readings:
        outcome = outcomes.get(r.loxone_vi)
        if outcome is None:
            status = None
            ok = r.value is None
        else:
            status = outcome.status
            ok = outcome.ok
        if ok:
            failure_streak[r.loxone_vi] = 0
        else:
            failure_streak[r.loxone_vi] = failure_streak.get(r.loxone_vi, 0) + 1
        states.append(
            ParameterState(
                loxone_vi=r.loxone_vi,
                path=r.path,
                unit=r.unit,
                value=r.value,
                last_loxone_status=status,
                consecutive_loxone_failures=failure_streak[r.loxone_vi],
            )
        )
    return states


def main() -> None:
    parser = argparse.ArgumentParser(prog="sitop-loxone-bridge bridge")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read once, send once, then exit. Useful for diagnostics.",
    )
    args, _ = parser.parse_known_args()

    settings = Settings()
    configure_logging(settings.log_level)
    log.info(
        "bridge.starting",
        opcua_url=settings.opcua_url,
        loxone_host=settings.loxone_host,
        data_dir=str(settings.data_dir),
        once=args.once,
    )
    sys.exit(asyncio.run(_run(settings, once=args.once)))
