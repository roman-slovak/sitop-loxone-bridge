from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

from sitop_loxone_bridge.opcua_reader import Reading

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LoxoneTarget:
    scheme: str
    host: str
    user: str
    password: str
    vi_power: str
    vi_voltage: str
    vi_current: str
    verify_ssl: bool = True


class LoxoneWriter:
    def __init__(self, target: LoxoneTarget, timeout_seconds: float = 5.0) -> None:
        self._target = target
        self._client = httpx.AsyncClient(
            auth=(target.user, target.password),
            timeout=timeout_seconds,
            verify=target.verify_ssl,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _vi_url(self, vi_name: str, value: float) -> str:
        # Loxone REST endpoint for Virtual Inputs.
        # Numeric value is sent as a URL path segment with a dot decimal separator.
        return (
            f"{self._target.scheme}://{self._target.host}"
            f"/dev/sps/io/{vi_name}/{value}"
        )

    async def _send_one(self, vi_name: str, value: float) -> None:
        url = self._vi_url(vi_name, value)
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            log.warning(
                "loxone.write_failed",
                vi=vi_name,
                value=value,
                url=url,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        if resp.is_success:
            return

        log.warning(
            "loxone.write_failed",
            vi=vi_name,
            value=value,
            url=url,
            status=resp.status_code,
            body=resp.text[:200],
        )

    async def send(self, reading: Reading) -> None:
        await asyncio.gather(
            self._send_one(self._target.vi_power, reading.power_w),
            self._send_one(self._target.vi_voltage, reading.voltage_v),
            self._send_one(self._target.vi_current, reading.current_a),
        )
