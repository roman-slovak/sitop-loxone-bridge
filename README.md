# sitop-loxone-bridge

Bridges a Siemens **SITOP PSU8600** power supply (OPC UA) into a **Loxone
Miniserver Energy Manager** via Virtual HTTP Inputs. Ships as two Docker
containers — a polling **bridge** and a small **web UI** for discovering
modules, picking which measurements to forward, and generating the Loxone
Config import file.

```
SITOP PSU8600         sitop-web (UI :8767)        Loxone Miniserver
opc.tcp://...112 ───┐                            ┌── /dev/sps/io/...
                    ├── sitop-bridge ────────────┤
                    │   reads selection.yaml     │
                    │   writes runtime_state.json│
                    └────── shared /data volume ─┘
```

## Quick start

```sh
cp .env.example .env
# edit .env: real LOXONE_HOST / LOXONE_USER / LOXONE_PASS
docker compose up -d --build
```

Open `http://localhost:8767/config`:

1. Click **Scan device** — the UI connects to the SITOP server, browses its
   address space and shows every measurable parameter grouped by module
   (Device, Output1..4, BUF8600, CNX8600).
2. Tick the parameters you want bridged. Edit the suggested Loxone VI names
   if you don't like them.
3. **Save selection** — bridge picks up the change within a few seconds
   (no restart).
4. **Download Loxone XML** — import the file in Loxone Config (Templates →
   Import). Save & load on the Miniserver.
5. Open `http://localhost:8767/` for the live dashboard.

## Architecture

Two services, one image, one shared volume:

| Service        | Command                                       | Purpose                                        |
| -------------- | --------------------------------------------- | ---------------------------------------------- |
| `sitop-bridge` | `python -m sitop_loxone_bridge bridge`        | 5 s poll loop, reads OPC UA → writes Loxone    |
| `sitop-web`    | `python -m sitop_loxone_bridge web` (uvicorn) | FastAPI on :8767 — discovery, selection, export|

Shared volume `sitop_data` (mounted as `/data` in both containers):

- `/data/selection.yaml` — written by web UI, watched by bridge (mtime reload)
- `/data/runtime_state.json` — written by bridge after every tick, read by web for the dashboard

## What ships in `selection.yaml`

```yaml
version: 1
opcua_url: opc.tcp://192.168.1.112:4840
generated_at: "2026-05-23T10:30:00+00:00"
parameters:
  - node_id: ns=3;i=100069
    path: PSU8600/Outputs/Output1/ActualState/OutputVoltage
    loxone_vi: SITOP_Out1_Voltage
    unit: V
    dtype: float
    min: 0.0
    max: 30.0
```

The bridge reads each `node_id`, formats the `value`, and GETs
`http://<LOXONE_HOST>/dev/sps/io/<loxone_vi>/<value>` with basic auth.

## Detected modules (SITOP PSU8600 V 1.5.2)

| Module       | Kind         | Example parameters                                                                  |
| ------------ | ------------ | ----------------------------------------------------------------------------------- |
| Device       | `device`     | `DeviceInputVoltage`, `DeviceOutputCurrent`, `DeviceUzkVoltage`, `DeviceMaxOutputCurrent` |
| Output1..4   | `output`     | `OutputVoltage`, `OutputCurrent`, `OperationState`, `ActualCurrentLimit`            |
| BUF8600_1    | `buffer`     | `ChargingCurrent`, `LoadCurrent`, `ChargingState`, `ModuleInternalBufferVoltage`    |
| CNX8600_1    | `controller` | `ModuleState`, `ModuleUzkVoltage`                                                   |

NodeIds and units are discovered live — no hardcoded mapping table.

## Loxone Template XML

`GET /api/export.xml` renders all currently saved parameters as a single
`<TemplateList>` of `<Template Type="VirtualInput">` elements, with `Title`,
`Unit`, `Min`, `Max`, `Format`, and a `Comment` linking back to the source
NodeId. The Jinja2 template at
`src/sitop_loxone_bridge/web/templates/loxone_template.xml.j2` is the single
source of truth — tweak it once you confirm the exact dialect your Loxone
Config version expects.

## Local development

```sh
uv sync
uv run pytest                                  # 21 unit tests
uv run python -m sitop_loxone_bridge bridge    # bridge only
uv run python -m sitop_loxone_bridge web       # web only on :8767
uv run python -m sitop_loxone_bridge.opcua_discovery  # quick CLI scan
```

## Logs

```sh
docker compose logs -f sitop-bridge
docker compose logs -f sitop-web
```

Successful bridge tick:

```json
{"event": "tick", "parameters": 8, "http_ok": 8, "http_fail": 0, ...}
```
