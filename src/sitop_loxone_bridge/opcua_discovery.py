"""SITOP PSU8600-aware OPC UA discovery.

Walks the canonical paths under `Objects/DeviceSet/PSU8600` and returns a
structured `ModuleTree` that groups variables by physical module (the chassis
itself, each Output, BUF8600/CNX8600 sub-devices). For every measurement leaf
the engineering unit and value range are looked up from the sibling
`EngineeringUnits` / `EURange` nodes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Iterable

import structlog
from asyncua import Client, Node, ua

log = structlog.get_logger(__name__)

# Variables we never want to surface as user-pickable measurements. These are
# either metadata children of a measurement (units, ranges) or things that are
# clearly internal (raw enums, certificate blobs, etc.).
_SKIP_BROWSE_NAMES = {
    "EngineeringUnits",
    "EURange",
    "EnumStrings",
    "InputArguments",
    "OutputArguments",
}


def _is_led_subobject(name: str) -> bool:
    # LED indicators (DeviceSupplyLed, DeviceOutputLed, OutputLed, …) just hold
    # Colour/State enums driving the front-panel LEDs. Not useful for Loxone.
    return name.endswith("Led")

# Output / Module OperationState enum index -> human label. 7 = active.
_OPERATION_STATE_ACTIVE = 7


@dataclass
class DiscoveredParameter:
    node_id: str
    browse_name: str
    path: str
    dtype: str
    unit: str = ""
    min: float | None = None
    max: float | None = None
    value: float | bool | int | None = None
    is_status: bool = False  # e.g. OperationState, ModuleState - useful for UI badges


@dataclass
class DiscoveredModule:
    name: str           # e.g. "Output1", "BUF8600_1", "Device"
    kind: str           # one of: "device", "output", "buffer", "controller", "other"
    path: str           # canonical browse path prefix
    active: bool = True
    parameters: list[DiscoveredParameter] = field(default_factory=list)


@dataclass
class ModuleTree:
    opcua_url: str
    product_name: str = ""
    firmware: str = ""
    modules: list[DiscoveredModule] = field(default_factory=list)


async def discover(
    url: str,
    *,
    username: str = "",
    password: str = "",
    session_timeout_ms: int = 120000,
    read_values: bool = True,
) -> ModuleTree:
    client = Client(url=url, timeout=15)
    client.session_timeout = session_timeout_ms
    if username:
        client.set_user(username)
    if password:
        client.set_password(password)

    await client.connect()
    try:
        return await _walk(client, url, read_values=read_values)
    finally:
        await client.disconnect()


async def _walk(client: Client, url: str, *, read_values: bool) -> ModuleTree:
    objects = client.nodes.objects
    device_set = await _child_by_name(objects, "DeviceSet")
    if device_set is None:
        raise RuntimeError("Objects/DeviceSet not found - is this really a SITOP server?")

    psu = await _child_by_name(device_set, "PSU8600")
    if psu is None:
        # Fall back to first DI device under DeviceSet.
        children = await device_set.get_children()
        psu = children[0] if children else None
    if psu is None:
        raise RuntimeError("No PSU device found under DeviceSet")

    tree = ModuleTree(opcua_url=url)
    tree.product_name, tree.firmware = await _read_identity(psu)

    # 1) Device-level (chassis) measurements: PSU8600/ActualState/*
    device_module = await _build_module(
        client,
        psu,
        name="Device",
        kind="device",
        sub_path=["ActualState"],
        read_values=read_values,
    )
    if device_module.parameters:
        tree.modules.append(device_module)

    # 2) Outputs: PSU8600/Outputs/Output{1..N}/ActualState/*
    outputs_node = await _child_by_name(psu, "Outputs")
    if outputs_node is not None:
        output_children = await outputs_node.get_children()
        for child in output_children:
            browse_name = (await child.read_browse_name()).Name
            if not browse_name.startswith("Output"):
                continue
            mod = await _build_module(
                client,
                child,
                name=browse_name,
                kind="output",
                sub_path=["ActualState"],
                read_values=read_values,
            )
            mod.active = _output_active(mod.parameters)
            tree.modules.append(mod)

    # 3) SubDevices: PSU8600/SubDevices/{BUF8600_*,CNX8600_*}/ActualState/*
    subdev_node = await _child_by_name(psu, "SubDevices")
    if subdev_node is not None:
        for child in await subdev_node.get_children():
            browse_name = (await child.read_browse_name()).Name
            if browse_name == "SupportedTypes":
                continue  # metadata, not a real module
            kind = _classify_subdevice(browse_name)
            mod = await _build_module(
                client,
                child,
                name=browse_name,
                kind=kind,
                sub_path=["ActualState"],
                read_values=read_values,
            )
            mod.active = _module_active(mod.parameters)
            tree.modules.append(mod)

    return tree


# --- helpers ---------------------------------------------------------------


async def _child_by_name(parent: Node, name: str) -> Node | None:
    for child in await parent.get_children():
        bn = await child.read_browse_name()
        if bn.Name == name:
            return child
    return None


async def _read_identity(psu: Node) -> tuple[str, str]:
    product = ""
    firmware = ""
    for label in ("Manufacturer", "ProductName", "Model"):
        node = await _child_by_name(psu, label)
        if node is not None:
            try:
                val = await node.read_value()
                if hasattr(val, "Text") and val.Text:
                    product = product or val.Text
                elif isinstance(val, str):
                    product = product or val
            except Exception:
                pass
    rev = await _child_by_name(psu, "RevisionCounter")
    if rev is not None:
        try:
            firmware = str(await rev.read_value())
        except Exception:
            pass
    return product, firmware


async def _build_module(
    client: Client,
    parent: Node,
    *,
    name: str,
    kind: str,
    sub_path: list[str],
    read_values: bool,
) -> DiscoveredModule:
    # Resolve parent + sub_path; return empty module if any segment missing.
    cursor: Node | None = parent
    for seg in sub_path:
        cursor = await _child_by_name(cursor, seg) if cursor else None
    base_path = await _browse_path(parent)
    full_prefix = "/".join([base_path, *sub_path])
    module = DiscoveredModule(name=name, kind=kind, path=full_prefix)
    if cursor is None:
        return module

    leaves = await _collect_measurement_leaves(cursor, base_path=full_prefix)
    if read_values and leaves:
        await _populate_values(client, leaves)
    module.parameters = leaves
    return module


async def _collect_measurement_leaves(
    root: Node, *, base_path: str
) -> list[DiscoveredParameter]:
    results: list[DiscoveredParameter] = []
    stack: list[tuple[Node, str]] = [(root, base_path)]
    while stack:
        node, path = stack.pop()
        try:
            children = await node.get_children()
        except Exception:
            children = []
        for child in children:
            try:
                node_class = await child.read_node_class()
                browse_name = (await child.read_browse_name()).Name
            except Exception:
                continue
            if browse_name in _SKIP_BROWSE_NAMES or _is_led_subobject(browse_name):
                continue
            child_path = f"{path}/{browse_name}"

            if node_class == ua.NodeClass.Variable:
                param = await _build_parameter(child, browse_name, child_path)
                if param is not None:
                    results.append(param)
            elif node_class == ua.NodeClass.Object:
                stack.append((child, child_path))
    return results


async def _build_parameter(
    node: Node, browse_name: str, path: str
) -> DiscoveredParameter | None:
    try:
        data_type_id = await node.read_data_type()
    except Exception:
        return None
    dtype = _dtype_label(data_type_id)
    if dtype not in {"float", "int", "bool"}:
        return None

    unit, low, high = await _read_unit_and_range(node)
    is_status = browse_name.lower().endswith("state") or browse_name in {"OperationState"}
    return DiscoveredParameter(
        node_id=node.nodeid.to_string(),
        browse_name=browse_name,
        path=path,
        dtype=dtype,
        unit=unit,
        min=low,
        max=high,
        is_status=is_status,
    )


def _dtype_label(data_type_id: ua.NodeId) -> str:
    # Built-in numeric/identifier mapping. Float types: Float (10), Double (11).
    # Int types: SByte..UInt64 (2..9). Bool: 1.
    if data_type_id.NamespaceIndex != 0 or not isinstance(data_type_id.Identifier, int):
        return "other"
    i = data_type_id.Identifier
    if i == 1:
        return "bool"
    if 2 <= i <= 9:
        return "int"
    if i in (10, 11):
        return "float"
    return "other"


async def _read_unit_and_range(
    node: Node,
) -> tuple[str, float | None, float | None]:
    unit = ""
    low: float | None = None
    high: float | None = None
    try:
        parent = await node.get_parent()
    except Exception:
        return unit, low, high
    if parent is None:
        return unit, low, high

    # Find sibling EngineeringUnits / EURange nodes (both live as children of
    # the parent next to the measurement node).
    for sibling in await parent.get_children():
        try:
            sname = (await sibling.read_browse_name()).Name
        except Exception:
            continue
        # The sibling lookup is name-based: SITOP places the unit/range nodes
        # as children of the measurement variable, not of its parent. Try both.
    # Measurement variables on SITOP have their EngineeringUnits/EURange as
    # *children* of the variable itself.
    for child in await node.get_children():
        try:
            cname = (await child.read_browse_name()).Name
        except Exception:
            continue
        if cname == "EngineeringUnits":
            try:
                eu = await child.read_value()
                if hasattr(eu, "DisplayName") and eu.DisplayName:
                    unit = eu.DisplayName.Text or ""
            except Exception:
                pass
        elif cname == "EURange":
            try:
                rng = await child.read_value()
                low = float(rng.Low)
                high = float(rng.High)
            except Exception:
                pass
    return unit, low, high


async def _populate_values(
    client: Client, params: Iterable[DiscoveredParameter]
) -> None:
    plist = list(params)
    if not plist:
        return
    nodes = [client.get_node(p.node_id) for p in plist]
    try:
        values = await client.read_values(nodes)
    except Exception as exc:
        log.warning("discovery.read_values_failed", error=str(exc))
        return
    for p, v in zip(plist, values):
        try:
            if p.dtype == "bool":
                p.value = bool(v)
            elif p.dtype == "int":
                p.value = int(v)
            else:
                p.value = float(v)
        except (TypeError, ValueError):
            p.value = None


async def _browse_path(node: Node) -> str:
    parts: list[str] = []
    cursor: Node | None = node
    # Walk up until Objects (i=85). Don't include "Objects" itself - too noisy.
    while cursor is not None:
        try:
            bn = await cursor.read_browse_name()
        except Exception:
            break
        if bn.Name == "Objects":
            break
        parts.append(bn.Name)
        try:
            cursor = await cursor.get_parent()
        except Exception:
            break
    return "/".join(reversed(parts))


def _classify_subdevice(name: str) -> str:
    upper = name.upper()
    if "BUF" in upper:
        return "buffer"
    if "CNX" in upper:
        return "controller"
    return "other"


def _output_active(params: Iterable[DiscoveredParameter]) -> bool:
    for p in params:
        if p.browse_name == "OperationState" and isinstance(p.value, int):
            return p.value == _OPERATION_STATE_ACTIVE
    return True  # If we couldn't read state, surface it as active.


def _module_active(params: Iterable[DiscoveredParameter]) -> bool:
    for p in params:
        if p.browse_name == "ModuleState" and isinstance(p.value, int):
            return p.value == _OPERATION_STATE_ACTIVE
    return True


# Make discovery runnable standalone for debugging:
#   uv run python -m sitop_loxone_bridge.opcua_discovery opc.tcp://192.168.1.112:4840
if __name__ == "__main__":  # pragma: no cover
    import sys

    async def _main() -> None:
        url = sys.argv[1] if len(sys.argv) > 1 else "opc.tcp://192.168.1.112:4840"
        tree = await discover(url)
        print(f"# {tree.product_name} @ {tree.opcua_url}")
        for m in tree.modules:
            status = "active" if m.active else "inactive"
            print(f"\n[{m.kind}] {m.name} ({status})")
            for p in m.parameters:
                v = f"{p.value} {p.unit}".strip() if p.value is not None else "-"
                print(f"  {p.browse_name:32} {p.node_id:16}  {v}")

    asyncio.run(_main())
