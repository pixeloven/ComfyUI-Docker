#!/usr/bin/env python3
"""Connect to an MCP server the way `claude --mcp-config <file>` would, with no agent.

usage: probe.py <config.json> [<tool> '<json args>']

Reads the one server in a Claude Code MCP config file, expands ${VAR} and
${VAR:-default} the way Claude Code does, then sends `initialize` and
`tools/list` over stdio or streamable HTTP, and optionally calls one tool (to
show the server reaches ComfyUI, not just that it speaks MCP). Prints the
server's name, version, instructions size and tool names; exits non-zero if the
handshake fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request

PROTOCOL = "2025-06-18"
TIMEOUT = 300
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": "harness-probe", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def expand(value):
    if isinstance(value, str):
        return re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}",
            lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""),
            value,
        )
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    return value


class Stdio:
    def __init__(self, cfg: dict):
        self.proc = subprocess.Popen(
            [cfg["command"], *cfg.get("args", [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **cfg.get("env", {})},
            text=True,
        )

    def send(self, msg: dict):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if "id" not in msg:
            return None
        for line in self.proc.stdout:
            if line.startswith("{"):
                reply = json.loads(line)
                if reply.get("id") == msg["id"]:
                    return reply
        raise RuntimeError(f"server closed stdout (exit {self.proc.poll()})")

    def close(self):
        self.proc.kill()
        self.proc.wait(timeout=10)


class Http:
    def __init__(self, cfg: dict):
        self.cfg, self.session = cfg, None

    def send(self, msg: dict):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        headers.update(self.cfg.get("headers", {}))
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(
            self.cfg["url"],
            data=json.dumps(msg).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            body = r.read().decode()
        if "id" not in msg:
            return None
        if body.lstrip().startswith("{"):
            return json.loads(body)
        for line in body.splitlines():  # text/event-stream
            if line.startswith("data:"):
                data = json.loads(line[5:])
                if data.get("id") == msg["id"]:
                    return data
        raise RuntimeError(f"no response to {msg['method']} in: {body[:200]!r}")

    def close(self):
        pass


def main() -> int:
    with open(sys.argv[1]) as f:
        servers = json.load(f)["mcpServers"]
    ((name, cfg),) = servers.items()
    cfg = expand(cfg)
    kind = cfg.get("type", "stdio")
    conn = Http(cfg) if kind in ("http", "streamable-http") else Stdio(cfg)
    try:
        init = conn.send(INIT)
        if "error" in init:
            print(f"{name}: initialize failed: {init['error']}")
            return 1
        conn.send(INITIALIZED)
        tools = conn.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        res = init["result"]
        names = sorted(t["name"] for t in tools.get("result", {}).get("tools", []))
        report = {
            "server": name,
            "transport": kind,
            "serverInfo": res.get("serverInfo"),
            "protocolVersion": res.get("protocolVersion"),
            "instructions_chars": len(res.get("instructions") or ""),
            "tool_count": len(names),
            "tools": names,
        }
        if len(sys.argv) > 3:
            tool, args = sys.argv[2], json.loads(sys.argv[3])
            reply = conn.send(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": args},
                }
            )
            result = reply.get("result", reply)
            text = "\n".join(c.get("text", "") for c in result.get("content", []))
            report["call"] = {
                "tool": tool,
                "isError": result.get("isError", False),
                "text": text[:600],
            }
        print(json.dumps(report, indent=2))
        return 0 if names and not report.get("call", {}).get("isError") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
