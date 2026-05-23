from __future__ import annotations

from dataclasses import dataclass

import structlog
from asyncua import Client, Node

from sitop_loxone_bridge.selection import SelectedParameter

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReadResult:
    loxone_vi: str
    path: str
    unit: str
    value: float | None


class OpcuaReader:
    """Reads an arbitrary list of selected parameters in one batched call."""

    def __init__(
        self,
        url: str,
        parameters: list[SelectedParameter],
        *,
        username: str = "",
        password: str = "",
        session_timeout_ms: int = 120000,
    ) -> None:
        self._url = url
        self._parameters = list(parameters)
        self._username = username
        self._password = password
        self._session_timeout_ms = session_timeout_ms
        self._client: Client | None = None
        self._nodes: list[Node] = []

    @property
    def parameters(self) -> list[SelectedParameter]:
        return list(self._parameters)

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        client = Client(url=self._url, timeout=10)
        client.session_timeout = self._session_timeout_ms
        if self._username:
            client.set_user(self._username)
        if self._password:
            client.set_password(self._password)
        await client.connect()
        self._client = client
        self._nodes = [client.get_node(p.node_id) for p in self._parameters]
        log.info("opcua.connected", url=self._url, parameters=len(self._parameters))

    async def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.disconnect()
        finally:
            self._client = None
            self._nodes = []
            log.info("opcua.disconnected")

    async def reconnect(self) -> None:
        await self.disconnect()
        await self.connect()

    async def read(self) -> list[ReadResult]:
        if self._client is None or not self._nodes:
            raise RuntimeError("OPC UA client is not connected")
        raw = await self._client.read_values(self._nodes)
        results: list[ReadResult] = []
        for param, value in zip(self._parameters, raw):
            try:
                if param.dtype == "bool":
                    coerced: float | None = float(bool(value))
                elif param.dtype == "int":
                    coerced = float(int(value))
                else:
                    coerced = float(value)
            except (TypeError, ValueError):
                coerced = None
            results.append(
                ReadResult(
                    loxone_vi=param.loxone_vi,
                    path=param.path,
                    unit=param.unit,
                    value=coerced,
                )
            )
        return results
