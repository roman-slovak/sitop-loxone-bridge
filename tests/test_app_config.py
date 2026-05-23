from pathlib import Path

import pytest

from sitop_loxone_bridge.app_config import AppConfig, load_app_config, save_app_config
from sitop_loxone_bridge.config import Settings


@pytest.fixture
def base_settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    monkeypatch.setenv("LOXONE_HOST", "192.168.1.10")
    monkeypatch.setenv("LOXONE_USER", "admin")
    monkeypatch.setenv("LOXONE_PASS", "secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return Settings()


def test_load_falls_back_to_env(base_settings: Settings) -> None:
    cfg = load_app_config(base_settings.app_config_path, fallback=base_settings)
    assert cfg.loxone_host == "192.168.1.10"
    assert cfg.opcua_url == "opc.tcp://192.168.1.112:4840"


def test_round_trip(base_settings: Settings) -> None:
    cfg = AppConfig.from_settings(base_settings).model_copy(
        update={"loxone_host": "10.0.0.5", "poll_interval_seconds": 2.5}
    )
    save_app_config(base_settings.app_config_path, cfg)
    loaded = load_app_config(base_settings.app_config_path, fallback=base_settings)
    assert loaded.loxone_host == "10.0.0.5"
    assert loaded.poll_interval_seconds == 2.5


def test_invalid_scheme_rejected() -> None:
    with pytest.raises(ValueError):
        AppConfig(
            opcua_url="opc.tcp://x",
            loxone_scheme="ftp",
            loxone_host="x",
            loxone_user="x",
            loxone_pass="x",
        )


def test_corrupt_yaml_returns_env_fallback(
    base_settings: Settings, tmp_path: Path
) -> None:
    base_settings.app_config_path.parent.mkdir(parents=True, exist_ok=True)
    base_settings.app_config_path.write_text("this is :: not :: valid :: yaml ::")
    cfg = load_app_config(base_settings.app_config_path, fallback=base_settings)
    # Should silently fall back, not crash.
    assert cfg.loxone_host == "192.168.1.10"
