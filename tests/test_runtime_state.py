import json
from pathlib import Path

from sitop_loxone_bridge.runtime_state import (
    ParameterState,
    RuntimeState,
    load_state,
    save_state,
)


def test_round_trip(tmp_path: Path) -> None:
    state = RuntimeState(
        opcua_connected=True,
        opcua_url="opc.tcp://x",
        ticks_total=10,
        parameters=[
            ParameterState(
                loxone_vi="A",
                value=1.0,
                unit="V",
                last_loxone_status=200,
            )
        ],
    )
    path = tmp_path / "state.json"
    save_state(path, state)

    loaded = load_state(path)
    assert loaded.ticks_total == 10
    assert loaded.parameters[0].value == 1.0


def test_corrupt_file_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not valid json {{{")
    loaded = load_state(path)
    assert loaded.ticks_total == 0
    assert loaded.parameters == []


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(path, RuntimeState())
    save_state(path, RuntimeState(ticks_total=1))
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == [], f"unexpected leftover files: {leftovers}"
    assert json.loads(path.read_text())["ticks_total"] == 1
