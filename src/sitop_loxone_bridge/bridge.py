from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

import structlog

from sitop_loxone_bridge.config import Settings
from sitop_loxone_bridge.loxone_writer import LoxoneTarget, LoxoneWriter
from sitop_loxone_bridge.opcua_reader import OpcuaReader

log = structlog.get_logger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    # asyncua's debug output is enormous (logs server certs, every byte of every
    # message). Keep it at WARNING unless explicitly debugging the OPC UA stack.
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


async def _run(settings: Settings, once: bool) -> int:
    reader = OpcuaReader(
        url=settings.opcua_url,
        node_input_voltage=settings.opcua_node_input_voltage,
        nodes_output_voltage=settings.output_voltage_nodes,
        nodes_output_current=settings.output_current_nodes,
        power_efficiency_factor=settings.power_efficiency_factor,
        username=settings.opcua_username,
        password=settings.opcua_password,
        session_timeout_ms=settings.opcua_session_timeout_ms,
    )
    writer = LoxoneWriter(
        target=LoxoneTarget(
            scheme=settings.loxone_scheme,
            host=settings.loxone_host,
            user=settings.loxone_user,
            password=settings.loxone_pass,
            vi_power=settings.loxone_vi_power,
            vi_voltage=settings.loxone_vi_voltage,
            vi_current=settings.loxone_vi_current,
            verify_ssl=settings.loxone_verify_ssl,
        )
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await reader.connect()
    consecutive_errors = 0
    try:
        while not stop_event.is_set():
            try:
                reading = await reader.read()
                await writer.send(reading)
                log.info(
                    "tick",
                    power_w=reading.power_w,
                    voltage_v=reading.voltage_v,
                    current_a=reading.current_a,
                )
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                log.error(
                    "tick.failed",
                    error=str(exc),
                    consecutive_errors=consecutive_errors,
                )
                # Exponential backoff capped at 60 s, kicks in after 5 failures.
                if consecutive_errors >= 5:
                    backoff = min(60.0, 2 ** (consecutive_errors - 5))
                    log.warning("opcua.reconnecting", backoff_seconds=backoff)
                    await asyncio.sleep(backoff)
                    try:
                        await reader.reconnect()
                    except Exception as recon_exc:
                        log.error("opcua.reconnect_failed", error=str(recon_exc))

            if once:
                break

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
    finally:
        await reader.disconnect()
        await writer.aclose()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="sitop-loxone-bridge")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read once, send once, then exit. Useful for diagnostics.",
    )
    args = parser.parse_args()

    settings = Settings()
    _configure_logging(settings.log_level)
    log.info(
        "bridge.starting",
        opcua_url=settings.opcua_url,
        loxone_host=settings.loxone_host,
        poll_interval=settings.poll_interval_seconds,
        once=args.once,
    )

    exit_code = asyncio.run(_run(settings, once=args.once))
    sys.exit(exit_code)
