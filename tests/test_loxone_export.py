from datetime import datetime

from sitop_loxone_bridge.loxone_export import render_loxone_template
from sitop_loxone_bridge.selection import SelectedParameter, Selection


def test_render_includes_all_parameters() -> None:
    selection = Selection(
        generated_at=datetime(2026, 5, 23, 10, 0, 0),
        parameters=[
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
        ],
    )
    xml = render_loxone_template(selection)
    assert '<?xml version="1.0" encoding="utf-8"?>' in xml
    assert "<TemplateList" in xml
    assert 'Title="SITOP_Out1_Voltage"' in xml
    assert 'Title="SITOP_Out1_Current"' in xml
    assert 'Unit="V"' in xml
    assert 'Unit="A"' in xml
    assert "<Min>0.0000</Min>" in xml
    assert "<Max>30.0000</Max>" in xml
    assert "PSU8600/Outputs/Output1/ActualState/OutputVoltage" in xml


def test_render_handles_missing_range() -> None:
    selection = Selection(
        parameters=[
            SelectedParameter(
                node_id="ns=3;i=1",
                path="x",
                loxone_vi="Foo",
                unit="",
                dtype="float",
            )
        ],
    )
    xml = render_loxone_template(selection)
    assert "<Min>" not in xml
    assert "<Max>" not in xml
    assert 'Title="Foo"' in xml
