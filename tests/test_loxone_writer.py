import httpx
import pytest
import respx

from sitop_loxone_bridge.loxone_writer import LoxoneTarget, LoxoneWriter


def _target() -> LoxoneTarget:
    return LoxoneTarget(
        scheme="http",
        host="miniserver.local",
        user="admin",
        password="secret",
    )


@pytest.mark.asyncio
@respx.mock
async def test_send_many_hits_each_endpoint() -> None:
    base = "http://miniserver.local/dev/sps/io"
    routes = [
        respx.get(f"{base}/SITOP_Power/42.5").mock(return_value=httpx.Response(200)),
        respx.get(f"{base}/SITOP_Voltage/230.1").mock(return_value=httpx.Response(200)),
        respx.get(f"{base}/SITOP_Current/0.18").mock(return_value=httpx.Response(200)),
    ]

    writer = LoxoneWriter(_target())
    try:
        outcomes = await writer.send_many(
            [
                ("SITOP_Power", 42.5),
                ("SITOP_Voltage", 230.1),
                ("SITOP_Current", 0.18),
            ]
        )
    finally:
        await writer.aclose()

    assert all(o.ok for o in outcomes)
    assert all(o.status == 200 for o in outcomes)
    for route in routes:
        assert route.called

    auth_header = routes[0].calls.last.request.headers.get("authorization", "")
    assert auth_header.startswith("Basic ")


@pytest.mark.asyncio
@respx.mock
async def test_send_one_returns_failure_on_error() -> None:
    respx.get(
        "http://miniserver.local/dev/sps/io/Broken/1.0"
    ).mock(return_value=httpx.Response(500))

    writer = LoxoneWriter(_target())
    try:
        outcome = await writer.send_one("Broken", 1.0)
    finally:
        await writer.aclose()

    assert outcome.ok is False
    assert outcome.status == 500


@pytest.mark.asyncio
@respx.mock
async def test_send_one_handles_transport_error() -> None:
    respx.get(
        "http://miniserver.local/dev/sps/io/Unreachable/1.0"
    ).mock(side_effect=httpx.ConnectError("boom"))

    writer = LoxoneWriter(_target())
    try:
        outcome = await writer.send_one("Unreachable", 1.0)
    finally:
        await writer.aclose()

    assert outcome.ok is False
    assert outcome.status is None
