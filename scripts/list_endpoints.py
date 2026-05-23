"""Print all endpoints offered by the OPC UA server.

Usage:
    uv run python scripts/list_endpoints.py [opc.tcp://192.168.1.112:4840]
"""

from __future__ import annotations

import asyncio
import sys

from asyncua import Client


async def main(url: str) -> None:
    client = Client(url=url)
    await client.connect_socket()
    try:
        await client.send_hello()
        await client.open_secure_channel()
        try:
            endpoints = await client.get_endpoints()
        finally:
            await client.close_secure_channel()
    finally:
        client.disconnect_socket()

    print(f"# {len(endpoints)} endpoints from {url}\n")
    for i, ep in enumerate(endpoints):
        print(f"--- endpoint {i} ---")
        print(f"  EndpointUrl:        {ep.EndpointUrl}")
        print(f"  SecurityMode:       {ep.SecurityMode}")
        print(f"  SecurityPolicyUri:  {ep.SecurityPolicyUri}")
        try:
            print(f"  ApplicationUri:     {ep.Server.ApplicationUri}")
            print(f"  ProductUri:         {ep.Server.ProductUri}")
        except Exception:
            pass
        tokens = []
        for tok in ep.UserIdentityTokens:
            tokens.append(f"{tok.TokenType}({tok.PolicyId})")
        print(f"  UserIdentityTokens: {', '.join(tokens)}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "opc.tcp://192.168.1.112:4840"
    asyncio.run(main(url))
