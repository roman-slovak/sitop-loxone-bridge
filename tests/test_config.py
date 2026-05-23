import pytest

from sitop_loxone_bridge.config import Settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPCUA_NODE_INPUT_VOLTAGE", "ns=3;i=100641")
    monkeypatch.setenv(
        "OPCUA_NODES_OUTPUT_VOLTAGE",
        "ns=3;i=100069,ns=3;i=100139,ns=3;i=100209,ns=3;i=100279",
    )
    monkeypatch.setenv(
        "OPCUA_NODES_OUTPUT_CURRENT",
        "ns=3;i=100061,ns=3;i=100131,ns=3;i=100201,ns=3;i=100271",
    )
    monkeypatch.setenv("LOXONE_HOST", "192.168.1.50")
    monkeypatch.setenv("LOXONE_USER", "admin")
    monkeypatch.setenv("LOXONE_PASS", "secret")


def test_settings_loads_defaults(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    settings = Settings()
    assert settings.opcua_url == "opc.tcp://192.168.1.112:4840"
    assert settings.poll_interval_seconds == 5.0
    assert settings.loxone_vi_power == "SITOP_Power"
    assert settings.loxone_verify_ssl is True
    assert settings.power_efficiency_factor == 1.0


def test_output_lists_parsed(monkeypatch: pytest.MonkeyPatch, chdir_tmp) -> None:
    _base_env(monkeypatch)
    settings = Settings()
    assert len(settings.output_voltage_nodes) == 4
    assert len(settings.output_current_nodes) == 4
    assert settings.output_voltage_nodes[0] == "ns=3;i=100069"


def test_poll_interval_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError):
        Settings()


def test_empty_output_voltage_list_rejected(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("OPCUA_NODES_OUTPUT_VOLTAGE", "")
    with pytest.raises(ValueError):
        Settings()


def test_overrides_via_env(monkeypatch: pytest.MonkeyPatch, chdir_tmp) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("LOXONE_VI_POWER", "Custom_Power")
    monkeypatch.setenv("POWER_EFFICIENCY_FACTOR", "1.075")
    settings = Settings()
    assert settings.poll_interval_seconds == 2.5
    assert settings.loxone_vi_power == "Custom_Power"
    assert settings.power_efficiency_factor == pytest.approx(1.075)
