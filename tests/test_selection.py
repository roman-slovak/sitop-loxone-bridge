from pathlib import Path

import pytest

from sitop_loxone_bridge.selection import (
    SelectedParameter,
    Selection,
    load_selection,
    save_selection,
)


def _params() -> list[SelectedParameter]:
    return [
        SelectedParameter(
            node_id="ns=3;i=100069",
            path="PSU8600/Outputs/Output1/ActualState/OutputVoltage",
            loxone_vi="SITOP_Out1_Voltage",
            unit="V",
            dtype="float",
            min=0.0,
            max=30.0,
        ),
        SelectedParameter(
            node_id="ns=3;i=100061",
            path="PSU8600/Outputs/Output1/ActualState/OutputCurrent",
            loxone_vi="SITOP_Out1_Current",
            unit="A",
            dtype="float",
            min=0.0,
            max=5.0,
        ),
    ]


def test_round_trip(tmp_path: Path) -> None:
    selection = Selection(parameters=_params())
    path = tmp_path / "selection.yaml"
    save_selection(path, selection)

    loaded = load_selection(path)
    assert loaded is not None
    assert len(loaded.parameters) == 2
    assert loaded.parameters[0].loxone_vi == "SITOP_Out1_Voltage"
    assert loaded.parameters[1].unit == "A"


def test_duplicate_vi_rejected() -> None:
    p = _params()
    p[1] = p[1].model_copy(update={"loxone_vi": "SITOP_Out1_Voltage"})
    with pytest.raises(ValueError, match="duplicate"):
        Selection(parameters=p)


def test_empty_vi_rejected() -> None:
    with pytest.raises(ValueError):
        SelectedParameter(
            node_id="ns=3;i=1",
            path="x",
            loxone_vi="   ",
        )


def test_forbidden_chars_in_vi_rejected() -> None:
    with pytest.raises(ValueError):
        SelectedParameter(
            node_id="ns=3;i=1",
            path="x",
            loxone_vi="bad name with spaces",
        )


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_selection(tmp_path / "nope.yaml") is None
