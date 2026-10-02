"""Run the comfyrelay MCP sidecar, and check one that is running.

    comfyctl relay serve                     start the server (reads its env; see below)
    comfyctl relay probe [URL]               check a running server, with no agent
    comfyctl relay docs build                build the docs index (the image does, at build time)

serve reads COMFYUI_MCP_HTTP_TOKEN (required: without it the server refuses to
start), COMFYUI_URL, MCP_HOST, MCP_PORT and COMFYUI_MCP_PROFILES. probe sends
the same COMFYUI_MCP_HTTP_TOKEN.

EXIT CODES, as every comfyctl group:

    0  did what was asked (probe: every check passed)
    1  a real failure (probe: a check failed; it says which; docs build: a
       fetch or build step failed)
    2  the request itself was wrong: no token, an unknown profile, a docs pin
       that is not a full commit SHA
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import sys
from pathlib import Path
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
    check_token,
)

# The server and the probe import the MCP SDK, so each command imports its own
# module when it runs: `comfyctl --help` and `comfyctl fetch` do not pay for it.

log = logging.getLogger("comfyrelay")

app = typer.Typer(
    name="relay",
    help=__doc__,
    no_args_is_help=True,
    rich_markup_mode="rich",
    # A crash must not print local variables: they hold tokens. Set explicitly,
    # so it holds on any Typer version the dependency floor allows.
    pretty_exceptions_show_locals=False,
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
    no_docs: Annotated[
        bool,
        typer.Option("--no-docs", help="Pass even if the server has no docs index (a server run from source)."),
    ] = False,
    output: OutputOpt = Mode.auto,
) -> None:
    """Check a running comfyrelay: 401 without the token, then initialize, tools/list and server_info with it,
    and that its docs index is built and docs_search finds something."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        typer.echo(f"{TOKEN_ENV} is not set: the probe needs the server's token", err=True)
        raise typer.Exit(2)
    try:
        check_token(token)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    from .probe import probe as run_probe

    report = asyncio.run(
        run_probe(url, token, timeout=timeout, require_comfyui=not no_comfyui, require_docs=not no_docs)
    )
    if output is Mode.json:
        json.dump(report.as_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        for check in report.checks:
            typer.echo(f"{'ok  ' if check.ok else 'FAIL'}  {check.name:<11} {check.detail}")
        typer.echo(f"probe: {'PASS' if report.ok else 'FAIL'} {report.url}")
    raise typer.Exit(0 if report.ok else 1)


docs_app = typer.Typer(
    name="docs",
    help="The docs index that docs_search and docs_guide read. The image builds it at build time.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
app.add_typer(docs_app)


@docs_app.command("build")
def docs_build(
    docs_sha: Annotated[
        str, typer.Option("--docs-sha", envvar="COMFY_DOCS_SHA", help="The Comfy-Org/docs commit to index (40 hex).")
    ],
    skills: Annotated[Path, typer.Option(help="The repository's skills/ directory: the guides are read from it.")],
    out: Annotated[Path, typer.Option(help="Where to write docs.sqlite, source/, NOTICE and GPL-3.0.txt.")],
    docs_repo: Annotated[str, typer.Option(help="The docs repository to fetch.")] = "https://github.com/Comfy-Org/docs",
    git_sha: Annotated[
        str,
        typer.Option(
            "--git-sha",
            envvar="GIT_SHA",
            help="The commit of this repository being built, for the guides' URLs and the NOTICE. "
            "Without it they point at the release tag of this version.",
        ),
    ] = "",
    output: OutputOpt = Mode.auto,
) -> None:
    """Fetch the docs at --docs-sha (shallow and sparse, with git) and build the docs index in --out."""
    import tempfile

    from .docs_index import COMMIT_SHA, GIT_SHA, DocsIndexError, build, fetch_docs

    if not COMMIT_SHA.fullmatch(docs_sha):
        typer.echo(f"--docs-sha must be a full 40-character commit SHA, not {docs_sha!r}", err=True)
        raise typer.Exit(2)
    git_sha = git_sha.strip()
    if git_sha and not GIT_SHA.fullmatch(git_sha):
        typer.echo(f"--git-sha must be a commit SHA (7 to 40 lowercase hex digits), not {git_sha!r}", err=True)
        raise typer.Exit(2)
    if not (skills / "comfyui-workflows" / "SKILL.md").is_file():
        typer.echo(f"{skills} has no comfyui-workflows/SKILL.md", err=True)
        raise typer.Exit(2)
    try:
        with tempfile.TemporaryDirectory(prefix="comfy-docs-") as tmp:
            fetch_docs(docs_repo, docs_sha, Path(tmp))
            summary = build(docs=Path(tmp), sha=docs_sha, skills=skills, out=out, git_sha=git_sha or None)
    except DocsIndexError as exc:
        typer.echo(f"docs build failed: {exc}", err=True)
        raise typer.Exit(1) from None
    if output is Mode.json:
        json.dump(summary, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    for source in summary["sources"]:
        typer.echo(
            f"{source['name']:<15} {source['version'][:12]:<12} {source['license']:<8} "
            f"{source['pages']} pages, {source['sections']} sections"
        )
    typer.echo(f"docs index: {out / 'docs.sqlite'}, {summary['bytes']} bytes, built in {summary['seconds']}s")
