from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LoxoneTarget:
    scheme: str
    host: str
    user: str
    password: str
    verify_ssl: bool = True


@dataclass(frozen=True)
class WriteOutcome:
    vi_name: str
    value: float
    status: int | None   # HTTP status code, or None for transport-level error
    ok: bool


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
        return (
            f"{self._target.scheme}://{self._target.host}"
            f"/dev/sps/io/{vi_name}/{value}"
        )

    async def send_one(self, vi_name: str, value: float) -> WriteOutcome:
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
            return WriteOutcome(vi_name=vi_name, value=value, status=None, ok=False)

        if not resp.is_success:
            log.warning(
                "loxone.write_failed",
                vi=vi_name,
                value=value,
                url=url,
                status=resp.status_code,
                body=resp.text[:200],
            )
        return WriteOutcome(
            vi_name=vi_name,
            value=value,
            status=resp.status_code,
            ok=resp.is_success,
        )

    async def send_many(
        self, items: list[tuple[str, float]]
    ) -> list[WriteOutcome]:
        if not items:
            return []
        coros = [self.send_one(name, value) for name, value in items]
        return await asyncio.gather(*coros)
