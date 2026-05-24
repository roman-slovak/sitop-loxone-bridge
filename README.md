# sitop-loxone-bridge

Bridges a Siemens **SITOP PSU8600** power supply (OPC UA) into a **Loxone
Miniserver Energy Manager** via Virtual HTTP Inputs. Ships as two Docker
containers — a polling **bridge** and a small **web UI** for discovering
modules, editing connection settings, picking which measurements to forward,
and generating the Loxone Config import file.

```
SITOP PSU8600         sitop-web (UI :8767)        Loxone Miniserver
opc.tcp://...112 ───┐                            ┌── /dev/sps/io/...
                    ├── sitop-bridge ────────────┤
                    │   reads selection.yaml     │
                    │   reads app_config.yaml    │
                    │   writes runtime_state.json│
                    └────── shared /data volume ─┘
```

## Quick start

```sh
cp .env.example .env
# .env is only bootstrap defaults — connection details can be edited later in the UI.
docker compose up -d --build
```

### Prebuilt image

GitHub Actions builds multi-arch (`linux/amd64`, `linux/arm64`) images on
every push to `main` and on tags. To use the prebuilt image instead of
building locally, swap the `build: .` lines in `docker-compose.yml` for:

```yaml
image: ghcr.io/roman-slovak/sitop-loxone-bridge:latest
```

Tags published: `latest` (main), `vX.Y.Z` (release tags), `sha-<short>`
(every commit).

Open `http://localhost:8767/config`:

1. **Connection settings** — set OPC UA URL and Loxone Miniserver host /
   user / password. Saved values land in `/data/app_config.yaml` and
   shadow `.env`; the bridge reconnects readers/writers automatically when
   relevant fields change.
2. **Scan device** — the UI connects to the SITOP server, browses its
   address space and shows every measurable parameter grouped by module
   (Computed, Device, Output1..N, BUF8600, CNX8600 + outputs). Panels are
   collapsed by default; the Computed group and modules that already have
   saved parameters auto-open.
3. **Pick parameters** with checkboxes. Suggested Loxone VI names are
   editable inline; "all"/"none" links work per module.
4. **Save selection** — bridge picks up the change within a few seconds
   (no restart).
5. **Download Loxone XML** — import the file in Loxone Config (Templates
   → Import). Save & load on the Miniserver.
6. Open `http://localhost:8767/` for the live dashboard with current
   values, HTTP statuses and a "Recent activity" log panel.

## Architecture

Two services, one image, one shared volume:

| Service        | Command                                       | Purpose                                        |
| -------------- | --------------------------------------------- | ---------------------------------------------- |
| `sitop-bridge` | `python -m sitop_loxone_bridge bridge`        | 5 s poll loop, reads OPC UA → writes Loxone    |
| `sitop-web`    | `python -m sitop_loxone_bridge web` (uvicorn) | FastAPI on :8767 — discovery, selection, export|

Shared volume `sitop_data` (mounted as `/data` in both containers):

- `/data/app_config.yaml` — editable runtime overlay over `.env` (OPC UA
  URL/creds, Loxone host/creds, poll interval). Written by the web UI,
  watched by the bridge (mtime reload, reconnects on change).
- `/data/selection.yaml` — selected parameters. Written by the web UI,
  watched by the bridge.
- `/data/runtime_state.json` — written by the bridge after every tick:
  per-parameter values, HTTP status, failure streak, connection state, and
  the last 60 captured log entries. Read by the web for the dashboard.

## Module discovery

The discovery walker handles the canonical SITOP layout and **expansion
modules** (e.g. **CNX8600/8X2.5A** adds 8 extra outputs at
`PSU8600/SubDevices/CNX8600_1/Outputs/Output{1..8}`):

| Module             | Kind         | Notes                                         |
| ------------------ | ------------ | --------------------------------------------- |
| Device             | `device`     | `DeviceInputVoltage`, `DeviceOutputCurrent`, … |
| Output1..N (main)  | `output`     | `OutputVoltage`, `OutputCurrent`, `OperationState`, … |
| `<sub>/Output1..M` | `output`     | Outputs on each expansion sub-device          |
| BUF8600_*          | `buffer`     | `ChargingCurrent`, `LoadCurrent`, `ChargingState`, … |
| CNX8600_*          | `controller` | `ModuleState`, `ModuleUzkVoltage`             |
| **Computed**       | `computed`   | Synthesised values (see below)                |

Units and ranges are read from the sibling `EngineeringUnits` / `EURange`
nodes. LED indicators (`*Led/Colour`, `*Led/State`) and OPC UA metadata
(`EnumStrings`, argument lists) are filtered out automatically.

## Derived/computed values

PSU8600 does not expose a direct input-power measurement, so the discovery
walker synthesises a **Computed** group with:

```
TotalOutputPower = Σ(OutputVoltage_i · OutputCurrent_i)
```

over every discovered output across all chassis. When selected, the
reader keeps the source NodeIds in `selection.yaml` and batch-reads them
once per tick — the sum is recomputed on the fly. Add an expansion module
and re-scan; the new outputs join the sum automatically.

The schema supports two aggregations today (`sum_product`, `sum`) and is
designed to grow without changing the persistence format.

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
  - node_id: derived:total_output_power
    path: Σ(OutputVoltage_i · OutputCurrent_i) across 12 outputs
    loxone_vi: SITOP_Power
    unit: W
    dtype: float
    aggregation: sum_product
    sources: [ns=3;i=100069, ns=3;i=100061, ns=3;i=100139, ns=3;i=100131, …]
```

The bridge reads each direct `node_id` and every `sources` entry,
formats the value, and GETs
`<scheme>://<LOXONE_HOST>/dev/sps/io/<loxone_vi>/<value>` with basic auth.

## Loxone Template XML

`GET /api/export.xml` renders all currently saved parameters as a single
`<TemplateList>` of `<Template Type="VirtualInput">` elements, with
`Title`, `Unit`, `Min`, `Max`, `Format`, and a `Comment` linking back to
the source NodeId. The Jinja2 template at
`src/sitop_loxone_bridge/web/templates/loxone_template.xml.j2` is the
single source of truth — tweak it once you confirm the exact dialect your
Loxone Config version expects.

## Connection & error handling

- **OPC UA**: stateful session. Read/connect failures disconnect the
  reader, log the error, and back off exponentially (2 → 60 s) before
  retrying. `runtime_state.opcua_connected = false` while degraded.
- **Loxone**: stateless HTTP via pooled `httpx.AsyncClient`. Per-VI
  failures are logged with status/body and reflected on the dashboard
  (`last_loxone_status`, `consecutive_loxone_failures`); next tick retries
  naturally.
- **Hot reload**: changes to `app_config.yaml` recreate only the affected
  client; changes to `selection.yaml` rebuild the reader.
- **Corrupt state files**: silently fall back to defaults — the web UI
  never refuses to start because a JSON file got truncated.
- **SIGINT/SIGTERM**: graceful shutdown closes both clients before exit.

## Recent activity panel

The bridge installs a structlog processor that mirrors every event into a
200-entry in-memory ring buffer. On each tick it snapshots the latest 60
into `runtime_state.json`, which the dashboard renders as a color-coded
log panel. Routine successful ticks (`tick … http_fail=0`) are filtered so
the panel stays focused on connects, reconnects, config reloads, write
failures, and any tick that lost a Loxone write.

`docker compose logs -f sitop-bridge` still shows the full JSON stream on
stdout.

## Healthcheck

Both containers expose Docker HEALTHCHECKs:

- `sitop-bridge` runs `python -m sitop_loxone_bridge.healthcheck`, which
  reads `runtime_state.json` and exits 0 if `last_tick` is within
  `HEALTH_FRESH_WINDOW_S` seconds (default 60 s), else 1.
- `sitop-web` probes `GET /healthz` locally and propagates the status.

External monitors can hit `http://<host>:8767/healthz` to get a JSON
body describing the bridge's freshness:

```json
{
  "status": "ok",
  "web_ok": true,
  "bridge_ok": true,
  "last_tick": "2026-05-24T10:30:00+00:00",
  "last_tick_age_s": 4.2,
  "fresh_window_s": 60
}
```

`HTTP 200` when `bridge_ok` is true, `503` otherwise. The web UI itself
keeps serving (`GET /` and the dashboard still return 200) even while
`/healthz` reports 503, so you can load the dashboard to investigate.
Note that because `sitop-web`'s Docker HEALTHCHECK probes `/healthz`,
both containers will show as `unhealthy` in `docker ps` when the bridge
is stuck — that's expected.

## Local development

```sh
uv sync
uv run pytest                                          # 35 unit tests
uv run python -m sitop_loxone_bridge bridge            # bridge only
uv run python -m sitop_loxone_bridge web               # web only on :8767
uv run python -m sitop_loxone_bridge.opcua_discovery   # quick CLI scan
```
