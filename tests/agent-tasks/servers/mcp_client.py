#!/usr/bin/env python3
"""The MCP client the harness gives every external agent, whatever the server.

usage (run every command from the same directory; its state files go there):
  mcp_client.py start [--spec FILE]
  mcp_client.py list
  mcp_client.py call TOOL ['<json arguments>' | @arguments.json]
  mcp_client.py stop

`start` reads the server's spec (default: server.json beside this file, which
external.sh writes) and launches a background broker that connects to the
server, sends `initialize` and `notifications/initialized`, and prints the
initialize result. The broker then holds that one connection, so state the
server keeps survives from one call to the next, and serves `list` and `call`
over a Unix socket. Its files, in the directory `start` ran in, are
.mcp-client.sock and .mcp-client.pid. `list` prints the tools/list result,
`call` the tools/call result, as JSON; both exit 1 on a JSON-RPC error or a
result with isError true. `stop` ends the connection.

The spec picks the transport:
  {"transport": "http", "url": ..., "token_file": ...}
      streamable HTTP: one POST per message with the bearer token read from
      token_file, the Mcp-Session-Id the server assigns, and replies as JSON
      or as a server-sent event stream.
  {"transport": "stdio", "command": [...], "env": {...}, "cwd": ..., "log": ...}
      newline-delimited JSON-RPC over the stdin and stdout of a process the
      broker starts and keeps running. It gets only PATH, TMPDIR and the
      locale variables from this environment, plus the spec's env; its stderr
      goes to the spec's log.

Stdlib only. The client is the same for every server: protocol 2025-06-18 and
no client capabilities. A request a server sends anyway is answered the way a
headless client answers it: `ping` with an empty result, `elicitation/create`
with action "cancel", anything else with method-not-found. It contacts nothing
but the server in its spec.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"
SOCK, PID = ".mcp-client.sock", ".mcp-client.pid"
TIMEOUT = 900  # seconds a single list or call may take
CLIENT_INFO = {"name": "harness-mcp-client", "version": "0"}
BASE_ENV = ("PATH", "TMPDIR", "LANG", "LANGUAGE")


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def base_env() -> dict[str, str]:
    """What a launched server inherits from this environment: nothing that could be a secret."""
    return {k: v for k, v in os.environ.items() if k in BASE_ENV or k.startswith("LC_")}


def answer_for(m: dict) -> dict:
    """The reply to a request the server sent us."""
    if m["method"] == "ping":
        reply = {"result": {}}
    elif m["method"] == "elicitation/create":
        reply = {"result": {"action": "cancel"}}
    else:
        reply = {"error": {"code": -32601, "message": f"{m['method']} is not supported by this client"}}
    return {"jsonrpc": "2.0", "id": m["id"], **reply}


def error(message: str) -> dict:
    return {"error": {"code": -32000, "message": message}}


# --- Transports: each has request(), notify() and stop() ---------------------------


class Stdio:
    def __init__(self, spec: dict):
        log = open(spec["log"], "ab") if spec.get("log") else subprocess.DEVNULL  # noqa: SIM115
        self.proc = subprocess.Popen(
            spec["command"],
            cwd=spec.get("cwd"),
            env={**base_env(), **spec.get("env", {})},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
        )
        self.next_id = 0

    def write(self, msg: dict) -> None:
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def notify(self, method: str) -> None:
        self.write({"jsonrpc": "2.0", "method": method})

    def request(self, method: str, params: dict | None) -> dict:
        self.next_id += 1
        rid = self.next_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self.write(msg)
        except OSError as e:
            return error(f"the server is gone ({e})")
        for raw in self.proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if "method" in m and "id" in m:  # a request from the server to us
                self.write(answer_for(m))
            elif m.get("id") == rid and "method" not in m:
                return m
            # anything else is a notification (progress, log): not ours to show
        return error(f"the server exited ({self.proc.wait()})")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Http:
    def __init__(self, spec: dict):
        self.url = spec["url"]
        with open(spec["token_file"]) as f:
            self.token = f.read().strip()
        self.session: str | None = None
        self.next_id = 0

    def post(self, msg: dict) -> str:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
            headers["MCP-Protocol-Version"] = PROTOCOL
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            return r.read().decode(errors="replace")

    def notify(self, method: str) -> None:
        self.post({"jsonrpc": "2.0", "method": method})

    def request(self, method: str, params: dict | None) -> dict:
        self.next_id += 1
        rid = self.next_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            body = self.post(msg)
        except urllib.error.HTTPError as e:
            return error(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        except (OSError, ValueError) as e:
            return error(f"the server did not answer ({e})")
        if body.lstrip().startswith("{"):
            messages = [body]
        else:  # text/event-stream: the JSON-RPC messages are on the data: lines
            messages = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        for raw in messages:
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if "method" in m and "id" in m:
                try:
                    self.post(answer_for(m))
                except (OSError, ValueError):
                    pass
            elif m.get("id") == rid and "method" not in m:
                return m
        return error(f"no reply to {method} in the server's response")

    def stop(self) -> None:
        pass


# --- The broker: owns the connection ------------------------------------------------


def recv_line(conn: socket.socket) -> bytes:
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            break
        buf += chunk
    return buf


def checked(req: object) -> str | None:
    """Why a request from a client command is malformed, or None."""
    if not isinstance(req, dict) or not isinstance(req.get("method"), str):
        return "a request needs a string method"
    if req.get("params") is not None and not isinstance(req["params"], dict):
        return "params must be an object"
    return None


def serve(spec: dict) -> None:
    """Run in the background by `start`. Reports one line on stdout (the initialize
    reply, or an error), then serves requests until `stop` or SIGTERM."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server = None
    try:
        try:
            server = Stdio(spec) if spec.get("transport") == "stdio" else Http(spec)
            init = server.request(
                "initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT_INFO}
            )
            if "error" not in init:
                server.notify("notifications/initialized")
        except (OSError, ValueError, KeyError) as e:
            init = error(f"could not reach the server: {e}")
        if "error" not in init:
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
                    req = None
                why = checked(req)
                if why:
                    reply = error(why)
                elif req["method"] == "stop":
                    conn.sendall(b'{"result":{}}\n')
                    return
                else:
                    try:
                        reply = server.request(req["method"], req.get("params"))
                    except Exception as e:  # noqa: BLE001  (keep serving whatever one request does)
                        reply = error(f"{type(e).__name__}: {e}")
                try:
                    conn.sendall((json.dumps(reply) + "\n").encode())
                except OSError:
                    pass
    finally:
        if server:
            server.stop()
        for p in (SOCK, PID):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass


# --- The commands the agent runs ---------------------------------------------------


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def broker_pid() -> int | None:
    try:
        with open(PID) as f:
            return int(f.read())
    except (OSError, ValueError):
        return None


def clear_stale() -> None:
    """Remove a socket or pid file whose broker is gone."""
    pid = broker_pid()
    if pid is None or not alive(pid):
        for p in (SOCK, PID):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass


def rpc(method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except OSError:
        die(f"no server connection from this directory ({SOCK}); run `start` first")
    with s:
        s.sendall((json.dumps({"method": method, "params": params}) + "\n").encode())
        line = recv_line(s)
    if not line:
        die("the client's broker closed the connection")
    return json.loads(line)


def show(reply: dict) -> None:
    print(json.dumps(reply.get("result", reply), indent=2))
    if "error" in reply or (reply.get("result") or {}).get("isError"):
        sys.exit(1)


def cmd_start(argv: list[str]) -> None:
    spec_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.json")
    if argv[:1] == ["--spec"] and len(argv) == 2:
        spec_file = argv[1]
    elif argv:
        die("usage: start [--spec FILE]")
    if os.path.exists(SOCK) or os.path.exists(PID):
        clear_stale()
        if os.path.exists(SOCK):
            die(f"a connection is already open from this directory ({SOCK}); run `stop` first")
    with open(spec_file) as f:
        spec = json.load(f)
    broker = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_serve", json.dumps(spec)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=open(spec["log"], "ab") if spec.get("log") else subprocess.DEVNULL,  # noqa: SIM115
        start_new_session=True,  # survives this shell; `stop` ends it
    )
    line = broker.stdout.readline()
    if not line:
        die("the server did not start")
    show(json.loads(line))


def cmd_stop() -> None:
    try:
        rpc("stop", timeout=30)
    except (OSError, SystemExit, ValueError):
        # Not answering (a call still running, or a stale socket): end it by pid.
        pid = broker_pid()
        if pid is not None and alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
    for _ in range(50):
        if not os.path.exists(SOCK):
            break
        time.sleep(0.2)
    clear_stale()
    print("stopped")


def main() -> None:
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "_serve":
        serve(json.loads(args[0]))
    elif cmd == "start":
        cmd_start(args)
    elif cmd == "list" and not args:
        show(rpc("tools/list"))
    elif cmd == "call" and 1 <= len(args) <= 2:
        raw = args[1] if len(args) == 2 else "{}"
        if raw.startswith("@"):
            with open(raw[1:]) as f:
                raw = f.read()
        try:
            arguments = json.loads(raw)
        except ValueError as e:
            die(f"the arguments are not JSON: {e}")
        show(rpc("tools/call", {"name": args[0], "arguments": arguments}))
    elif cmd == "stop" and not args:
        cmd_stop()
    else:
        die(__doc__.split("\n\n")[1])


if __name__ == "__main__":
    main()
