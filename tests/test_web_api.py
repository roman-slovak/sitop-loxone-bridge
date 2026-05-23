import os
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from sitop_loxone_bridge.config import Settings
from sitop_loxone_bridge.selection import SelectedParameter, Selection, save_selection
from sitop_loxone_bridge.web.app import create_app


@pytest.fixture
def app_with_tmp_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LOXONE_HOST", "192.168.1.1")
    monkeypatch.setenv("LOXONE_USER", "admin")
    monkeypatch.setenv("LOXONE_PASS", "pw")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings()
    return create_app(settings), settings


@pytest.mark.asyncio
async def test_dashboard_renders(app_with_tmp_dir) -> None:
    app, _settings = app_with_tmp_dir
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
        assert r.status_code == 200
        assert "Bridge status" in r.text


@pytest.mark.asyncio
async def test_state_endpoint_returns_defaults(app_with_tmp_dir) -> None:
    app, _ = app_with_tmp_dir
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/state")
        assert r.status_code == 200
        body = r.json()
        assert body["ticks_total"] == 0
        assert body["parameters"] == []


@pytest.mark.asyncio
async def test_selection_put_then_get(app_with_tmp_dir) -> None:
    app, _ = app_with_tmp_dir
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = {
            "parameters": [
                {
                    "node_id": "ns=3;i=100069",
                    "path": "PSU8600/Outputs/Output1/ActualState/OutputVoltage",
                    "loxone_vi": "SITOP_Out1_Voltage",
                    "unit": "V",
                    "dtype": "float",
                    "min": 0.0,
                    "max": 30.0,
                }
            ]
        }
        r = await client.put("/api/selection", json=payload)
        assert r.status_code == 200
        assert r.json()["saved"] is True

        r2 = await client.get("/api/selection")
        assert r2.status_code == 200
        body = r2.json()
        assert body["exists"] is True
        assert body["parameters"][0]["loxone_vi"] == "SITOP_Out1_Voltage"


@pytest.mark.asyncio
async def test_export_requires_selection(app_with_tmp_dir) -> None:
    app, _ = app_with_tmp_dir
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/export.xml")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_returns_xml_after_save(app_with_tmp_dir) -> None:
    app, settings = app_with_tmp_dir
    save_selection(
        settings.selection_path,
        Selection(
            parameters=[
                SelectedParameter(
                    node_id="ns=3;i=1",
                    path="x",
                    loxone_vi="Foo",
                    unit="V",
                    dtype="float",
                )
            ]
        ),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/export.xml")
        assert r.status_code == 200
        assert "TemplateList" in r.text
        assert 'Title="Foo"' in r.text
        assert "attachment" in r.headers.get("content-disposition", "")
