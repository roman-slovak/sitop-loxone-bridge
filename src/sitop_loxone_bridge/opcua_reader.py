from __future__ import annotations

from dataclasses import dataclass

import structlog
from asyncua import Client, Node

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Reading:
    power_w: float
    voltage_v: float
    current_a: float


class OpcuaReader:
    """Reads SITOP PSU8600 measurements.

    The PSU8600 does not expose total input power directly. We send:
      * voltage_v = AC input voltage (single node)
      * power_w   = efficiency_factor * sum(Vout_i * Iout_i) over all outputs
      * current_a = sum(Iout_i) over all outputs (DC, informational)
    """

    def __init__(
        self,
        url: str,
        node_input_voltage: str,
        nodes_output_voltage: list[str],
        nodes_output_current: list[str],
        power_efficiency_factor: float = 1.0,
        username: str = "",
        password: str = "",
        session_timeout_ms: int = 120000,
    ) -> None:
        if len(nodes_output_voltage) != len(nodes_output_current):
            raise ValueError(
                "nodes_output_voltage and nodes_output_current must be the same length"
            )
        self._url = url
        self._username = username
        self._password = password
        self._session_timeout_ms = session_timeout_ms
        self._node_input_voltage = node_input_voltage
        self._nodes_v = list(nodes_output_voltage)
        self._nodes_i = list(nodes_output_current)
        self._efficiency = power_efficiency_factor
        self._client: Client | None = None
        self._batch: list[Node] = []

    async def connect(self) -> None:
        client = Client(url=self._url, timeout=10)
        client.session_timeout = self._session_timeout_ms
        if self._username:
            client.set_user(self._username)
        if self._password:
            client.set_password(self._password)
        await client.connect()
        self._client = client
        # Order in self._batch: [input_voltage, v1, v2, ..., vN, i1, i2, ..., iN]
        self._batch = [client.get_node(self._node_input_voltage)]
        self._batch.extend(client.get_node(n) for n in self._nodes_v)
        self._batch.extend(client.get_node(n) for n in self._nodes_i)
        log.info(
            "opcua.connected",
            url=self._url,
            outputs=len(self._nodes_v),
        )

    async def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.disconnect()
        finally:
            self._client = None
            self._batch = []
            log.info("opcua.disconnected")

    async def reconnect(self) -> None:
        await self.disconnect()
        await self.connect()

    async def read(self) -> Reading:
        if self._client is None or not self._batch:
            raise RuntimeError("OPC UA client is not connected")

        values = await self._client.read_values(self._batch)
        n = len(self._nodes_v)
        input_voltage = float(values[0])
        voltages = [float(v) for v in values[1 : 1 + n]]
        currents = [float(v) for v in values[1 + n : 1 + 2 * n]]
        dc_power = sum(v * i for v, i in zip(voltages, currents))
        return Reading(
            power_w=round(self._efficiency * dc_power, 3),
            voltage_v=round(input_voltage, 2),
            current_a=round(sum(currents), 3),
        )
