#!/usr/bin/env python3
"""Talk to a stdio MCP server from separate shell commands, keeping one server process alive.

usage (run every command from the same directory; its state files go there):
  stdio_client.py start [--cwd DIR] [--env NAME=VALUE ...] -- COMMAND [ARGS...]
  stdio_client.py list
  stdio_client.py call TOOL ['<json arguments>' | @arguments.json]
  stdio_client.py stop

`start` launches a background broker that runs COMMAND (in DIR, with the extra
environment), sends `initialize` and `notifications/initialized`, and prints
the initialize result. The broker then holds that one server process, so state
the server keeps survives from one call to the next, and serves `list` and
`call` over a Unix socket. Its files, in the directory `start` ran in, are
.mcp-stdio.sock, .mcp-stdio.pid and .mcp-stdio.log (the server's stderr).
`list` prints the tools/list result, `call` the tools/call result, as JSON;
both exit 1 on a JSON-RPC error or a result with isError true. `stop` ends the
server.

Stdlib only. It contacts nothing but the process it started: messages go over
that process's stdin and stdout as newline-delimited JSON-RPC 2.0, and the
socket is a local Unix socket. A request the server sends to the client is
answered the way a headless client answers it: `ping` with an empty result,
`elicitation/create` with action "cancel", anything else with method-not-found.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time

PROTOCOL = "2025-06-18"
SOCK, PID, LOG = ".mcp-stdio.sock", ".mcp-stdio.pid", ".mcp-stdio.log"
TIMEOUT = 900  # seconds a single list or call may take


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


# --- The broker: owns the server process ------------------------------------------


class Server:
    def __init__(self, command: list[str], cwd: str | None, env: dict[str, str]):
        self.proc = subprocess.Popen(
            command,
            cwd=cwd,
            env={**os.environ, **env},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(LOG, "ab"),  # noqa: SIM115 (lives as long as the broker)
        )
        self.next_id = 0

    def write(self, msg: dict) -> None:
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None) -> dict:
        self.next_id += 1
        rid = self.next_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.write(msg)
        for raw in self.proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if "method" in m and "id" in m:  # a request from the server to us
                self.answer(m)
            elif m.get("id") == rid and "method" not in m:
                return m
            # anything else is a notification (progress, log): not ours to show
        return {"error": {"code": -32000, "message": f"server exited ({self.proc.wait()}); see {LOG}"}}

    def answer(self, m: dict) -> None:
        if m["method"] == "ping":
            reply = {"result": {}}
        elif m["method"] == "elicitation/create":
            reply = {"result": {"action": "cancel"}}
        else:
            reply = {"error": {"code": -32601, "message": f"{m['method']} is not supported by this client"}}
        self.write({"jsonrpc": "2.0", "id": m["id"], **reply})

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def recv_line(conn: socket.socket) -> bytes:
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            break
        buf += chunk
    return buf


def serve(cwd: str | None, env: dict[str, str], command: list[str]) -> None:
    """Run in the background by `start`. Reports one line on stdout (the initialize
    reply, or an error), then serves requests until `stop` or SIGTERM."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server = None
    try:
        server = Server(command, cwd, env)
        init = server.request(
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "stdio_client", "version": "0"}},
        )
        if "error" not in init:
            server.write({"jsonrpc": "2.0", "method": "notifications/initialized"})
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(SOCK)
            srv.listen()
            with open(PID, "w") as f:
                f.write(str(os.getpid()))
        print(json.dumps(init), flush=True)
        if "error" in init:
            return
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 1)
        while True:
            conn, _ = srv.accept()
            with conn:
                try:
                    req = json.loads(recv_line(conn))
                except ValueError:
                    continue
                if req.get("method") == "stop":
                    conn.sendall(b'{"result":{}}\n')
                    return
                reply = server.request(req["method"], req.get("params"))
                conn.sendall((json.dumps(reply) + "\n").encode())
    finally:
        if server:
            server.stop()
        for p in (SOCK, PID):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass


# --- The commands the agent runs ---------------------------------------------------


def rpc(method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except OSError:
        die(f"no server running from this directory ({SOCK}); run `start` first")
    with s:
        s.sendall((json.dumps({"method": method, "params": params}) + "\n").encode())
        line = recv_line(s)
    if not line:
        die(f"the broker closed the connection; see {LOG}")
    return json.loads(line)


def show(reply: dict) -> None:
    print(json.dumps(reply.get("result", reply), indent=2))
    if "error" in reply or (reply.get("result") or {}).get("isError"):
        sys.exit(1)


def cmd_start(argv: list[str]) -> None:
    if "--" not in argv:
        die("usage: start [--cwd DIR] [--env NAME=VALUE ...] -- COMMAND [ARGS...]")
    opts, command = argv[: argv.index("--")], argv[argv.index("--") + 1 :]
    if not command:
        die("start: no COMMAND after --")
    if os.path.exists(SOCK):
        die(f"a server is already running from this directory ({SOCK}); run `stop` first")
    cwd, env = None, {}
    while opts:
        flag = opts.pop(0)
        if flag == "--cwd" and opts:
            cwd = opts.pop(0)
        elif flag == "--env" and opts and "=" in opts[0]:
            k, v = opts.pop(0).split("=", 1)
            env[k] = v
        else:
            die(f"start: unexpected {flag!r}")
    broker = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_serve", json.dumps({"cwd": cwd, "env": env, "command": command})],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=open(LOG, "ab"),  # noqa: SIM115
        start_new_session=True,  # survives this shell; `stop` ends it
    )
    line = broker.stdout.readline()
    if not line:
        die(f"the server did not start; see {LOG}")
    show(json.loads(line))


def cmd_stop() -> None:
    try:
        rpc("stop", timeout=30)
    except (OSError, SystemExit):
        # Not answering (a call still running, or a stale socket): end it by pid.
        try:
            pid = int(open(PID).read())
            os.killpg(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
    for _ in range(50):
        if not os.path.exists(SOCK):
            break
        time.sleep(0.2)
    print("stopped")


def main() -> None:
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "_serve":
        spec = json.loads(args[0])
        serve(spec["cwd"], spec["env"], spec["command"])
    elif cmd == "start":
        cmd_start(args)
    elif cmd == "list" and not args:
        show(rpc("tools/list"))
    elif cmd == "call" and 1 <= len(args) <= 2:
        raw = args[1] if len(args) == 2 else "{}"
        if raw.startswith("@"):
            with open(raw[1:]) as f:
                raw = f.read()
        show(rpc("tools/call", {"name": args[0], "arguments": json.loads(raw)}))
    elif cmd == "stop" and not args:
        cmd_stop()
    else:
        die(__doc__.split("\n\n")[1])


if __name__ == "__main__":
    main()
