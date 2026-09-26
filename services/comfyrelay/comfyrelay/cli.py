"""Run the comfyrelay MCP sidecar, and check one that is running.

    comfyctl relay serve                     start the server (reads its env; see below)
    comfyctl relay probe [URL]               check a running server, with no agent

serve reads COMFYUI_MCP_HTTP_TOKEN (required: without it the server refuses to
start), COMFYUI_URL, MCP_HOST, MCP_PORT and COMFYUI_MCP_PROFILES. probe sends
the same COMFYUI_MCP_HTTP_TOKEN.

EXIT CODES, as every comfyctl group:

    0  did what was asked (probe: every check passed)
    1  a real failure (probe: a check failed; it says which)
    2  the request itself was wrong: no token, an unknown profile
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import sys
from typing import Annotated

import typer

from .settings import (
    DEFAULT_COMFYUI_URL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PROFILES,
    DEFAULT_PROBE_URL,
    PROFILES,
    PROFILES_ENV,
    TOKEN_ENV,
    ConfigError,
    Settings,
)

# The server and the probe import the MCP SDK, so each command imports its own
# module when it runs: `comfyctl --help` and `comfyctl fetch` do not pay for it.

log = logging.getLogger("comfyrelay")

app = typer.Typer(
    name="relay",
    help=__doc__,
    no_args_is_help=True,
    rich_markup_mode="rich",
)


class Mode(str, enum.Enum):
    auto = "auto"
    plain = "plain"
    json = "json"


OutputOpt = Annotated[
    Mode,
    typer.Option("--output", "-o", help="auto or plain: text lines. json: machine-readable."),
]


class _JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {"time": record.created, "level": record.levelname, "logger": record.name, "message": record.getMessage()}
        )


def _configure_logging(mode: Mode) -> None:
    # Set before the server is built: MCPServer calls logging.basicConfig,
    # which does nothing once the root logger has a handler.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _JsonLines() if mode is Mode.json else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


@app.command()
def serve(
    comfyui_url: Annotated[
        str, typer.Option("--comfyui-url", envvar="COMFYUI_URL", help="Where ComfyUI answers, from here.")
    ] = DEFAULT_COMFYUI_URL,
    host: Annotated[str, typer.Option(envvar="MCP_HOST", help="Listen address.")] = DEFAULT_HOST,
    port: Annotated[int, typer.Option(envvar="MCP_PORT", help="Listen port. The path is /mcp.")] = DEFAULT_PORT,
    profiles: Annotated[
        str,
        typer.Option(envvar=PROFILES_ENV, help=f"Comma-separated capability profiles, from {', '.join(PROFILES)}."),
    ] = ",".join(DEFAULT_PROFILES),
    output: OutputOpt = Mode.auto,
) -> None:
    """Serve MCP over streamable HTTP at /mcp. Refuses to start without COMFYUI_MCP_HTTP_TOKEN."""
    _configure_logging(output)
    try:
        settings = Settings.load(comfyui_url=comfyui_url, host=host, port=port, profiles=profiles)
    except ConfigError as exc:
        log.error("%s", exc)
        raise typer.Exit(2) from exc
    from .server import serve as run_server

    run_server(settings)


@app.command()
def probe(
    url: Annotated[str, typer.Argument(help="The server's MCP endpoint.")] = DEFAULT_PROBE_URL,
    timeout: Annotated[float, typer.Option(help="Seconds to wait on each request.")] = 30.0,
    no_comfyui: Annotated[
        bool,
        typer.Option("--no-comfyui", help="Pass even if the server cannot reach ComfyUI (a build-time check)."),
    ] = False,
    output: OutputOpt = Mode.auto,
) -> None:
    """Check a running comfyrelay: 401 without the token, then initialize, tools/list and server_info with it."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        typer.echo(f"{TOKEN_ENV} is not set: the probe needs the server's token", err=True)
        raise typer.Exit(2)
    from .probe import probe as run_probe

    report = asyncio.run(run_probe(url, token, timeout=timeout, require_comfyui=not no_comfyui))
    if output is Mode.json:
        json.dump(report.as_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        for check in report.checks:
            typer.echo(f"{'ok  ' if check.ok else 'FAIL'}  {check.name:<11} {check.detail}")
        typer.echo(f"probe: {'PASS' if report.ok else 'FAIL'} {url}")
    raise typer.Exit(0 if report.ok else 1)
