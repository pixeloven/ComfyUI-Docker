"""The check that needs no agent: is a running comfyrelay usable?

It is what CI runs, what the image runs at build time, and what an operator runs
after deploying. It connects the way an MCP client does and checks, in order:

    reachable   something answers at the URL
    auth        a request WITHOUT the token is refused with 401
    token       a request WITH the token is not
    initialize  the MCP handshake succeeds
    tools       tools/list includes server_info
    server_info the call succeeds and returns the identity fields
    docs        server_info says the docs index is built, and docs_search finds
                something (skipped with --no-docs)
    comfyui     server_info says ComfyUI is reachable (skipped with --no-comfyui)

Each failed check names what it saw. Later checks do not run once one that
they depend on has failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx2
import mcp_types as types
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from . import __version__
from .settings import redact_url

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "comfyctl-relay-probe", "version": __version__},
    },
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    url: str
    checks: list[Check] = field(default_factory=list)
    server: dict[str, Any] | None = None
    tools: list[str] = field(default_factory=list)
    server_info: dict[str, Any] | None = None
    docs_hits: int | None = None  # what docs_search found, when the probe called it

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str) -> bool:
        self.checks.append(Check(name, ok, detail))
        return ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "url": self.url,
            "checks": [c.__dict__ for c in self.checks],
            "server": self.server,
            "tools": self.tools,
            "server_info": self.server_info,
            "docs_hits": self.docs_hits,
        }


def _leaf(exc: BaseException) -> BaseException:
    """The first real error inside the task-group wrappers the client raises."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


async def _session(
    report: Report, http: httpx2.AsyncClient, url: str, timeout: float, docs: bool
) -> dict[str, Any] | None:
    """initialize, tools/list, server_info, and docs_search when `docs`. Returns server_info's result, or None
    after a failed check."""
    async with Client(
        streamable_http_client(url, http_client=http),
        mode="legacy",
        read_timeout_seconds=timeout,
        client_info=types.Implementation(name="comfyctl-relay-probe", version=__version__),
    ) as client:
        info = client.server_info
        report.server = info.model_dump(exclude_none=True) if info else None
        report.add(
            "initialize",
            True,
            f"{info.name if info else '?'} {info.version if info else '?'}, protocol {client.protocol_version}",
        )

        tools = await client.list_tools()
        report.tools = sorted(t.name for t in tools.tools)
        if not report.add(
            "tools",
            "server_info" in report.tools,
            f"{len(report.tools)} tools: {', '.join(report.tools) or 'none'}",
        ):
            return None

        result = await client.call_tool("server_info", {})
        data = result.structured_content
        if result.is_error or not isinstance(data, dict):
            text = " ".join(getattr(c, "text", "") for c in result.content)
            report.add("server_info", False, f"the call failed: {text[:300]}")
            return None
        report.server_info = data
        active = ",".join(data.get("profiles", {}).get("active", []))
        report.add("server_info", True, f"instance {data.get('instance_id')}, profiles {active}")
        if docs and "docs_search" in report.tools and (data.get("docs") or {}).get("status") == "built":
            found = await client.call_tool("docs_search", {"query": "ComfyUI", "limit": 1})
            hits = found.structured_content if not found.is_error else None
            report.docs_hits = len(hits.get("results", [])) if isinstance(hits, dict) else 0
        return data


async def probe(
    url: str, token: str, *, timeout: float = 30.0, require_comfyui: bool = True, require_docs: bool = True
) -> Report:
    shown = redact_url(url)  # what is rendered; `url` is what is requested
    report = Report(url=shown)

    async with httpx2.AsyncClient(timeout=timeout) as anonymous:
        try:
            r = await anonymous.post(url, json=_INITIALIZE, headers={"Accept": "application/json, text/event-stream"})
        except httpx2.TransportError as exc:
            report.add("reachable", False, f"nothing answers at {shown}: {type(exc).__name__}: {exc}")
            return report
    report.add("reachable", True, f"{shown} answers")
    if not report.add(
        "auth",
        r.status_code == 401,
        f"a request without the token got HTTP {r.status_code}"
        + ("" if r.status_code == 401 else "; the endpoint must refuse it with 401"),
    ):
        return report

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=timeout) as http:
        # A GET with no session opens nothing; any answer but 401 means the token passed.
        r = await http.get(url, headers={"Accept": "text/event-stream"})
        if not report.add(
            "token",
            r.status_code != 401,
            "the server accepts this token"
            if r.status_code != 401
            else "the server refused this token with 401: it is not the server's COMFYUI_MCP_HTTP_TOKEN",
        ):
            return report
        try:
            data = await _session(report, http, url, timeout, require_docs)
        except Exception as exc:  # anything the client raises is a failed handshake or call
            leaf = _leaf(exc)
            report.add("initialize" if report.server is None else "call", False, f"{type(leaf).__name__}: {leaf}")
            return report
    if data is None:
        return report

    docs = data.get("docs") or {}
    if not require_docs:
        report.add("docs", True, f"not required (--no-docs); status {docs.get('status')}")
    elif docs.get("status") != "built":
        report.add("docs", False, f"server_info.docs is {docs.get('status')!r}: {docs.get('reason')}")
    elif "docs_search" not in report.tools:
        report.add("docs", True, f"{docs.get('pages')} pages built; docs_search is not in the active profiles")
    else:
        versions = ", ".join(f"{s.get('name')} {str(s.get('version'))[:12]}" for s in docs.get("sources", []))
        report.add(
            "docs",
            bool(report.docs_hits),
            f"{docs.get('pages')} pages ({versions}); docs_search found {report.docs_hits or 'nothing'}",
        )

    comfy = data.get("comfyui") or {}
    if comfy.get("reachable"):
        pin = comfy.get("pinned_version") or "unknown"
        report.add(
            "comfyui",
            True,
            f"ComfyUI {comfy.get('live_version')} reachable (built for {pin}, matches: {comfy.get('matches_pin')})",
        )
    else:
        why = (comfy.get("error") or {}).get("message", "no reason given")
        if require_comfyui:
            report.add("comfyui", False, f"the server cannot reach ComfyUI: {why}")
        else:
            report.add("comfyui", True, f"not required (--no-comfyui); unreachable: {why}")
    return report
