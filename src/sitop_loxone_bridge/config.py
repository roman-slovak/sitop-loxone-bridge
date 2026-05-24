from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- OPC UA ---
    opcua_url: str = "opc.tcp://192.168.1.112:4840"
    opcua_username: str = ""
    opcua_password: str = ""
    opcua_session_timeout_ms: int = 120000

    # --- Loxone ---
    loxone_scheme: str = "http"
    loxone_host: str
    loxone_user: str
    loxone_pass: str
    loxone_verify_ssl: bool = True

    # --- Bridge runtime ---
    poll_interval_seconds: float = Field(default=5.0, gt=0)
    log_level: str = "INFO"
    health_fresh_window_s: float = Field(default=60.0, gt=0)

    # --- Web ---
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8765, ge=1, le=65535)

    # --- Shared state files (volume-mounted in Docker) ---
    data_dir: Path = Path("/data")

    @property
    def selection_path(self) -> Path:
        return self.data_dir / "selection.yaml"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "runtime_state.json"

    @property
    def export_xml_path(self) -> Path:
        return self.data_dir / "sitop_loxone_template.xml"

    @property
    def app_config_path(self) -> Path:
        return self.data_dir / "app_config.yaml"
