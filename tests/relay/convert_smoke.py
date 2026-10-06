"""The mcp-convert image's conversion smoke (#167), run by run.sh INSIDE the relay container, with its Python:

    docker exec -i -e COMFYUI_MCP_HTTP_TOKEN=... -e RELAY_URL=http://127.0.0.1:9000/mcp <relay> \
      python - < convert_smoke.py

It picks the first open-source template this ComfyUI serves that has a subgraph and is under 30,000 characters,
converts it through the relay's MCP tools (template_get with format="api", then workflow_validate with the UI
graph), and checks both against the frontend's own Export (API) of the same template, made in this run by the
image's own Chromium with nothing blocked, in a fresh context. Prints one JSON line; exits 1 on any mismatch.
"""

import asyncio
import json
import os
import sys
import time

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from playwright.async_api import async_playwright

RELAY = os.environ["RELAY_URL"]
TOKEN = os.environ["COMFYUI_MCP_HTTP_TOKEN"]
COMFYUI = os.environ["COMFYUI_URL"].rstrip("/")
READY = "() => !!(window.app && window.app.graphToPrompt && window.app.loadGraphData && window.app.vueAppReady)"
EXPORT = """async (wf) => {
  await window.app.loadGraphData(wf, true, false, null);
  return JSON.parse(JSON.stringify((await window.app.graphToPrompt()).output));
}"""


def fail(why: str, **out) -> None:
    print(json.dumps({"ok": False, "why": why, **out}))
    sys.exit(1)


async def pick() -> tuple[str, dict]:
    async with httpx2.AsyncClient(base_url=COMFYUI, timeout=60) as http:
        index = (await http.get("/templates/index.json")).json()
        for c in index:
            for t in c.get("templates", []):
                if t.get("openSource") is False:
                    continue
                wf = (await http.get(f"/templates/{t['name']}.json")).json()
                if (wf.get("definitions") or {}).get("subgraphs") and len(json.dumps(wf)) < 30_000:
                    return t["name"], wf
    fail("no open-source template with a subgraph under 30,000 characters is served")


async def export(wf: dict) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await (await browser.new_context()).new_page()
            await page.goto(COMFYUI, wait_until="load")
            await page.wait_for_function(READY, polling=250, timeout=60_000)
            return await page.evaluate(EXPORT, wf)
        finally:
            await browser.close()


async def call(mcp: Client, tool: str, args: dict) -> dict:
    result = await mcp.call_tool(tool, args)
    if result.is_error:
        fail(f"{tool} failed", error=result.content[0].text[:500])
    return result.structured_content


async def main() -> None:
    name, wf = await pick()
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120) as http:
        transport = streamable_http_client(RELAY, http_client=http)
        async with Client(transport, mode="legacy", read_timeout_seconds=120) as mcp:
            before = (await call(mcp, "server_info", {}))["capabilities"]["conversion"]
            if before["state"] not in ("ready", "running"):
                fail("the relay does not convert", conversion=before)
            t0 = time.monotonic()
            got = await call(mcp, "template_get", {"name": name, "format": "api"})
            cold = time.monotonic() - t0
            t0 = time.monotonic()
            again = await call(mcp, "template_get", {"name": name, "format": "api"})
            warm = time.monotonic() - t0
            checked = await call(mcp, "workflow_validate", {"workflow": wf})
            after = (await call(mcp, "server_info", {}))["capabilities"]["conversion"]
    want = await export(wf)
    out = {
        "template": name,
        "nodes": len(want),
        "cold_s": round(cold, 2),
        "warm_s": round(warm, 2),
        "frontend_version": after.get("frontend_version"),
    }
    if not out["frontend_version"]:
        fail("server_info does not report the frontend version the converter loaded", **out)
    if not (got["converted_from_ui"] and got["format"] == "api"):
        fail("template_get did not say it converted", **out)
    if got["workflow"] != want or again["workflow"] != want:
        fail("template_get's API graph differs from the frontend's own export", **out)
    if not checked["converted_from_ui"] or checked["workflow"] != want:
        fail("workflow_validate's converted graph differs from the frontend's own export", **out)
    print(json.dumps({"ok": True, **out}))


asyncio.run(main())
