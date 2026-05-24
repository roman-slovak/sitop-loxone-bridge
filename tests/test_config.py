import pytest

from sitop_loxone_bridge.config import Settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOXONE_HOST", "192.168.1.50")
    monkeypatch.setenv("LOXONE_USER", "admin")
    monkeypatch.setenv("LOXONE_PASS", "secret")


def test_settings_loads_defaults(monkeypatch: pytest.MonkeyPatch, chdir_tmp) -> None:
    _base_env(monkeypatch)
    settings = Settings()
    assert settings.opcua_url == "opc.tcp://192.168.1.112:4840"
    assert settings.poll_interval_seconds == 5.0
    assert settings.web_port == 8765
    assert str(settings.selection_path).endswith("selection.yaml")
    assert str(settings.state_path).endswith("runtime_state.json")


def test_poll_interval_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError):
        Settings()


def test_data_dir_override(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp, tmp_path
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings()
    assert settings.selection_path.parent == tmp_path


def test_health_fresh_window_default(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    settings = Settings()
    assert settings.health_fresh_window_s == 60.0


def test_health_fresh_window_override(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("HEALTH_FRESH_WINDOW_S", "30")
    settings = Settings()
    assert settings.health_fresh_window_s == 30.0


def test_health_fresh_window_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, chdir_tmp
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("HEALTH_FRESH_WINDOW_S", "0")
    with pytest.raises(ValueError):
        Settings()
