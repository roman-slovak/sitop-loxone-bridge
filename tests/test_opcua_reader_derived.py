from typing import Any

import pytest

from sitop_loxone_bridge.opcua_reader import OpcuaReader, _compute_derived
from sitop_loxone_bridge.selection import SelectedParameter


class FakeClient:
    """Stub that mimics asyncua's Client.read_values for unit testing."""

    def __init__(self, values_by_node: dict[str, float]) -> None:
        self._values = values_by_node

    def get_node(self, node_id: str) -> str:
        return node_id  # the reader uses these only as keys

    async def read_values(self, nodes: list[str]) -> list[Any]:
        return [self._values[n] for n in nodes]

    async def disconnect(self) -> None:
        pass


@pytest.mark.asyncio
async def test_reader_handles_mixed_direct_and_derived(monkeypatch) -> None:
    values = {
        "ns=3;i=v1": 24.0,
        "ns=3;i=i1": 0.5,
        "ns=3;i=v2": 24.0,
        "ns=3;i=i2": 0.25,
        "ns=3;i=other": 215.0,
    }
    params = [
        SelectedParameter(
            node_id="ns=3;i=other",
            path="x",
            loxone_vi="SITOP_Voltage",
            dtype="float",
            unit="V",
        ),
        SelectedParameter(
            node_id="derived:total_output_power",
            path="Σ V·I",
            loxone_vi="SITOP_Power",
            dtype="float",
            unit="W",
            aggregation="sum_product",
            sources=["ns=3;i=v1", "ns=3;i=i1", "ns=3;i=v2", "ns=3;i=i2"],
        ),
    ]
    reader = OpcuaReader(url="opc.tcp://x", parameters=params)
    reader._client = FakeClient(values)  # type: ignore[assignment]
    reader._nodes = [reader._client.get_node(nid) for nid in reader._batch_ids]  # type: ignore[union-attr]

    results = await reader.read()
    by_vi = {r.loxone_vi: r.value for r in results}
    assert by_vi["SITOP_Voltage"] == 215.0
    assert by_vi["SITOP_Power"] == pytest.approx(24.0 * 0.5 + 24.0 * 0.25)


def test_batch_ids_dedupes_sources_and_direct() -> None:
    params = [
        SelectedParameter(
            node_id="ns=3;i=v1",
            path="x",
            loxone_vi="A",
            dtype="float",
        ),
        SelectedParameter(
            node_id="derived:foo",
            path="y",
            loxone_vi="B",
            dtype="float",
            aggregation="sum_product",
            sources=["ns=3;i=v1", "ns=3;i=i1"],
        ),
    ]
    reader = OpcuaReader(url="opc.tcp://x", parameters=params)
    assert reader._batch_ids == ["ns=3;i=v1", "ns=3;i=i1"]


def test_compute_sum_product_odd_sources_returns_none() -> None:
    p = SelectedParameter(
        node_id="derived:x",
        path="x",
        loxone_vi="X",
        aggregation="sum_product",
        sources=["a", "b", "c"],
    )
    assert _compute_derived(p, {"a": 1, "b": 2, "c": 3}) is None


def test_compute_sum() -> None:
    p = SelectedParameter(
        node_id="derived:x",
        path="x",
        loxone_vi="X",
        aggregation="sum",
        sources=["a", "b", "c"],
    )
    assert _compute_derived(p, {"a": 1, "b": 2, "c": 3}) == 6.0
