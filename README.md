# sitop-loxone-bridge

Reads input power, voltage and current from a Siemens SITOP PSU8600 power
supply via OPC UA and forwards the values to a Loxone Miniserver as Virtual
HTTP Inputs, where they can be wired into the Energy Manager block.

```
SITOP PSU8600  ──opc.tcp──▶  bridge (Docker)  ──HTTP GET──▶  Loxone Miniserver
192.168.1.112                                                    Energy Manager
```

## Loxone Config setup

In Loxone Config create three **Virtual HTTP Inputs** with these exact names
(must match `LOXONE_VI_*` in `.env`):

| Name              | Unit | Energy Manager role                |
| ----------------- | ---- | ---------------------------------- |
| `SITOP_Power`     | W    | Consumer (used for consumption)    |
| `SITOP_Voltage`   | V    | Diagnostic only                    |
| `SITOP_Current`   | A    | Diagnostic only                    |

The bridge calls each input as:

```
http://<user>:<pass>@<miniserver>/dev/sps/io/<VI_NAME>/<value>
```

## What the bridge actually sends

The SITOP PSU8600 does **not** expose a direct input-power or input-current
measurement. The bridge derives them by summing the per-output DC values:

- `SITOP_Power`   = `POWER_EFFICIENCY_FACTOR × Σ(OutputVoltage_i × OutputCurrent_i)`
- `SITOP_Voltage` = `DeviceInputVoltage` (AC line, single node)
- `SITOP_Current` = `Σ(OutputCurrent_i)` (DC, informational)

Set `POWER_EFFICIENCY_FACTOR=1.0` to send the raw DC output sum, or use
`1.075` (`= 1 / 0.93`) to estimate AC consumption assuming ~93% efficiency.

## NodeIds for SITOP PSU8600 V 1.5.2

These are baked into `.env.example` after live-browsing the server at
`192.168.1.112`. If you have a different firmware or output configuration,
re-discover them with:

```sh
uv run python scripts/discover_nodes.py > nodes.tsv
grep -E 'DeviceInputVoltage|Output[1-4].*ActualState.*(OutputVoltage|OutputCurrent)$' nodes.tsv
```

| What                       | Path                                                                 | NodeId           |
| -------------------------- | -------------------------------------------------------------------- | ---------------- |
| AC input voltage           | `PSU8600/ActualState/DeviceInputVoltage`                              | `ns=3;i=100641`  |
| Output 1 voltage / current | `PSU8600/Outputs/Output1/ActualState/OutputVoltage` / `OutputCurrent` | `100069` / `100061` |
| Output 2 voltage / current | `PSU8600/Outputs/Output2/...`                                         | `100139` / `100131` |
| Output 3 voltage / current | `PSU8600/Outputs/Output3/...`                                         | `100209` / `100201` |
| Output 4 voltage / current | `PSU8600/Outputs/Output4/...`                                         | `100279` / `100271` |

## Run locally

```sh
cp .env.example .env
# edit .env: real LOXONE_HOST/USER/PASS and OPC UA node IDs

uv sync
uv run python -m sitop_loxone_bridge --once   # single-shot diagnostic
uv run python -m sitop_loxone_bridge          # continuous loop
```

## Run with Docker

```sh
docker compose up -d --build
docker compose logs -f
```

Each successful cycle logs a JSON line like:

```json
{"event": "tick", "power_w": 42.1, "voltage_v": 230.4, "current_a": 0.18, ...}
```

## Tests

```sh
uv run pytest
```
