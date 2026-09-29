"""Terminal demo for the README GIF: calls the real AppFactory MCP tools and prints the results.

Recorded with VHS (`vhs docs/demo/demo.tape`). Everything shown is live App Store data from the tools.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

B, D, G, Y, C, M, R = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[36m", "\033[35m", "\033[0m"


def out(text: str = "", delay: float = 0.0) -> None:
    print(text, flush=True)
    time.sleep(delay)


def typed(text: str, speed: float = 0.03) -> None:
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(speed)
    print()


def call(name: str, args: str) -> None:
    out(f"  {M}●{R} {B}appfactory{R} {D}·{R} {name}({D}{args}{R})", 0.4)


def fmt_price(p: dict) -> str:
    return p.get("price", "")


async def main() -> None:
    env = {**os.environ, "HOME": tempfile.mkdtemp(prefix="demo-")}
    server = StdioTransport("uv", ["run", "--quiet", "--directory", os.getcwd(), "appfactory-mcp"], env=env)
    async with Client(server) as c:
        out(f"{B}{C}AppFactory{R} {D}· MCP server · idea → TestFlight{R}", 0.6)
        out()
        sys.stdout.write(f"{B}›{R} ")
        typed("Find an underserved iOS niche around water tracking and validate it")
        out("", 0.4)

        call("idea_evaluate", 'term="water tracker", country="us"')
        r = (await c.call_tool("idea_evaluate", {"term": "water tracker", "country": "us",
                                                  "name_candidates": ["Sipwell", "Hydrate", "AquaLog"]})).data
        n, comp = r["niche"], r["niche"]["competition"]
        out()
        verdict = G if n["verdict"] == "GO" else Y
        out(f"  {B}Niche score{R}   {verdict}{B}{n['score']} / {n['verdict']}{R}", 0.3)
        out(f"  {B}Demand{R}        {r['autocomplete']['demand']} {D}({r['autocomplete']['count']} autocomplete terms){R}", 0.3)
        out(f"  {B}Competition{R}   {round(comp['weak_ratio'] * 100)}% of top apps have < 1k ratings, "
            f"{round(comp['stale_ratio'] * 100)}% not updated in 6 months", 0.3)
        nt = r["newcomer_traction"]["window_12mo"]
        out(f"  {B}Newcomers{R}     {nt['count']} launched in the last 12 months, best one has {nt['best']} ratings", 0.3)
        for leader in [x for x in r["leaders"] if x.get("price_ladder")][:2]:
            prices = sorted({fmt_price(p) for p in leader["price_ladder"]}, key=lambda s: float(s.strip("$") or 0))
            out(f"  {B}Leader{R}        {leader['name'][:32]} {D}· {leader['ratings']:,} ratings · IAPs {prices[0]}–{prices[-1]}{R}", 0.3)
        na = r.get("name_availability") or {}
        taken = [x["name"] for x in na.get("checked", []) if not x.get("available")]
        if na.get("available_name"):
            out(f"  {B}Name{R}          {G}{na['available_name']}{R} is free on the App Store"
                + (f" {D}({', '.join(taken)} taken){R}" if taken else ""), 0.3)
        out()
        out(f"{D}Next: say{R} {B}Run AppFactory{R} {D}to build it:{R}", 0.5)
        out(f"  {D}design research → SwiftUI app → backend → subscriptions → ASO + screenshots → TestFlight{R}", 0.3)
        out(f"  {D}every irreversible step waits for{R} {B}appfactory approve <id>{R} {D}in your terminal{R}", 2.5)


if __name__ == "__main__":
    asyncio.run(main())
