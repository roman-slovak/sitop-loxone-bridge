import httpx
import pytest
import respx

from sitop_loxone_bridge.loxone_writer import LoxoneTarget, LoxoneWriter
from sitop_loxone_bridge.opcua_reader import Reading


def _target() -> LoxoneTarget:
    return LoxoneTarget(
        scheme="http",
        host="miniserver.local",
        user="admin",
        password="secret",
        vi_power="SITOP_Power",
        vi_voltage="SITOP_Voltage",
        vi_current="SITOP_Current",
    )


@pytest.mark.asyncio
@respx.mock
async def test_send_hits_three_vi_endpoints() -> None:
    base = "http://miniserver.local/dev/sps/io"
    power_route = respx.get(f"{base}/SITOP_Power/42.5").mock(
        return_value=httpx.Response(200)
    )
    voltage_route = respx.get(f"{base}/SITOP_Voltage/230.1").mock(
        return_value=httpx.Response(200)
    )
    current_route = respx.get(f"{base}/SITOP_Current/0.18").mock(
        return_value=httpx.Response(200)
    )

    writer = LoxoneWriter(_target())
    try:
        await writer.send(Reading(power_w=42.5, voltage_v=230.1, current_a=0.18))
    finally:
        await writer.aclose()

    assert power_route.called
    assert voltage_route.called
    assert current_route.called

    auth_header = power_route.calls.last.request.headers.get("authorization", "")
    assert auth_header.startswith("Basic ")


@pytest.mark.asyncio
@respx.mock
async def test_send_swallows_http_errors() -> None:
    base = "http://miniserver.local/dev/sps/io"
    respx.get(f"{base}/SITOP_Power/1.0").mock(return_value=httpx.Response(500))
    respx.get(f"{base}/SITOP_Voltage/2.0").mock(return_value=httpx.Response(200))
    respx.get(f"{base}/SITOP_Current/3.0").mock(
        side_effect=httpx.ConnectError("boom")
    )

    writer = LoxoneWriter(_target())
    try:
        # Must not raise even when individual calls fail.
        await writer.send(Reading(power_w=1.0, voltage_v=2.0, current_a=3.0))
    finally:
        await writer.aclose()
