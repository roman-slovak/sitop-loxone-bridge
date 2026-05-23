"""Browse SITOP PSU8600 OPC UA address space and print all variable NodeIds with their browse paths.

Usage:
    uv run python scripts/discover_nodes.py [opc.tcp://192.168.1.112:4840]
"""

from __future__ import annotations

import asyncio
import sys

from asyncua import Client, Node, ua


async def walk(node: Node, path: list[str], max_depth: int, lines: list[str]) -> None:
    if len(path) > max_depth:
        return
    try:
        node_class = await node.read_node_class()
    except Exception:
        return

    if node_class == ua.NodeClass.Variable:
        try:
            value = await node.read_value()
            data_type = type(value).__name__
        except Exception as exc:
            value = f"<read error: {exc}>"
            data_type = "?"
        nid = node.nodeid.to_string()
        full_path = " / ".join(path)
        lines.append(f"{nid}\t{data_type}\t{value!r}\t{full_path}")

    try:
        children = await node.get_children()
    except Exception:
        return

    for child in children:
        try:
            bname = await child.read_browse_name()
            label = bname.Name
        except Exception:
            label = child.nodeid.to_string()
        await walk(child, path + [label], max_depth, lines)


async def main(url: str) -> None:
    print(f"# Connecting to {url}", file=sys.stderr)
    client = Client(url=url, timeout=30)
    client.session_timeout = 120000
    async with client:
        # Standard root: Objects folder (NodeId i=85)
        objects = client.nodes.objects
        lines: list[str] = []
        await walk(objects, ["Objects"], max_depth=8, lines=lines)
        print("NodeId\tType\tValue\tPath")
        for line in lines:
            print(line)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "opc.tcp://192.168.1.112:4840"
    asyncio.run(main(url))
