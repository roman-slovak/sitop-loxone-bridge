from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    opcua_url: str = "opc.tcp://192.168.1.112:4840"
    opcua_username: str = ""
    opcua_password: str = ""
    opcua_session_timeout_ms: int = 120000

    # Single node: AC line voltage at the SITOP input.
    opcua_node_input_voltage: str

    # Comma-separated NodeIds, paired by position.
    # Total DC output power = sum(Vi * Ii); total DC current = sum(Ii).
    opcua_nodes_output_voltage: str
    opcua_nodes_output_current: str

    # Multiplier applied to DC output power before sending. 1.0 = report DC
    # output sum as-is. Use e.g. 1.075 (i.e. 1/0.93) to estimate AC consumption
    # assuming ~93% efficiency.
    power_efficiency_factor: float = Field(default=1.0, gt=0)

    loxone_scheme: str = "http"
    loxone_host: str
    loxone_user: str
    loxone_pass: str
    loxone_verify_ssl: bool = True

    loxone_vi_power: str = "SITOP_Power"
    loxone_vi_voltage: str = "SITOP_Voltage"
    loxone_vi_current: str = "SITOP_Current"

    poll_interval_seconds: float = Field(default=5.0, gt=0)
    log_level: str = "INFO"

    @property
    def output_voltage_nodes(self) -> list[str]:
        return _split_csv(self.opcua_nodes_output_voltage)

    @property
    def output_current_nodes(self) -> list[str]:
        return _split_csv(self.opcua_nodes_output_current)

    @field_validator("opcua_nodes_output_voltage", "opcua_nodes_output_current")
    @classmethod
    def _non_empty_list(cls, v: str) -> str:
        if not _split_csv(v):
            raise ValueError("must contain at least one NodeId")
        return v
