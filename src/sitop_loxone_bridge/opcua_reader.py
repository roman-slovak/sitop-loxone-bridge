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
    """Reads a mixed list of direct + derived parameters in one batched call."""

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

        # Collect every distinct OPC UA NodeId we need to read each tick:
        # direct params themselves plus the source NodeIds of any derived ones.
        self._batch_ids: list[str] = []
        seen: set[str] = set()
        for p in self._parameters:
            if not p.is_derived:
                if p.node_id not in seen:
                    self._batch_ids.append(p.node_id)
                    seen.add(p.node_id)
            for src in p.sources:
                if src not in seen:
                    self._batch_ids.append(src)
                    seen.add(src)
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
        self._nodes = [client.get_node(nid) for nid in self._batch_ids]
        log.info(
            "opcua.connected",
            url=self._url,
            parameters=len(self._parameters),
            unique_nodes=len(self._batch_ids),
        )

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
        if self._client is None:
            raise RuntimeError("OPC UA client is not connected")
        # Batch-read every unique source NodeId once.
        if self._nodes:
            raw = await self._client.read_values(self._nodes)
        else:
            raw = []
        by_node = dict(zip(self._batch_ids, raw))

        results: list[ReadResult] = []
        for param in self._parameters:
            if param.is_derived:
                value = _compute_derived(param, by_node)
            else:
                value = _coerce(by_node.get(param.node_id), param.dtype)
            results.append(
                ReadResult(
                    loxone_vi=param.loxone_vi,
                    path=param.path,
                    unit=param.unit,
                    value=value,
                )
            )
        return results


def _coerce(value: object, dtype: str) -> float | None:
    if value is None:
        return None
    try:
        if dtype == "bool":
            return float(bool(value))
        if dtype == "int":
            return float(int(value))  # type: ignore[arg-type]
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _compute_derived(
    param: SelectedParameter, by_node: dict[str, object]
) -> float | None:
    agg = param.aggregation
    if agg == "sum_product":
        if not param.sources or len(param.sources) % 2 != 0:
            return None
        total = 0.0
        for v_id, i_id in zip(param.sources[0::2], param.sources[1::2]):
            v = _coerce(by_node.get(v_id), "float")
            i = _coerce(by_node.get(i_id), "float")
            if v is None or i is None:
                return None
            total += v * i
        return round(total, 3)
    if agg == "sum":
        total = 0.0
        for sid in param.sources:
            v = _coerce(by_node.get(sid), "float")
            if v is None:
                return None
            total += v
        return round(total, 3)
    return None
