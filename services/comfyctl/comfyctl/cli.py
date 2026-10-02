"""comfyctl — one command for ComfyUI-Docker's tooling.

Each tool is a group, mounted from its own package rather than reimplemented:

    comfyctl fetch build|resolve|fetch|check|facts   manifest, lock and verified model downloads

Every group follows the same conventions, because automation reads them:

    --output auto|plain|json   auto colours at a terminal and goes plain when
                               piped; json gives stable keys for agents.
    stdout                     carries the result, so `> lock.yaml` and `| jq` work
    stderr                     carries progress and problems

    exit 0   did what was asked
    exit 1   a real failure: a source did not resolve, a hash did not match
    exit 2   the request itself was wrong: a missing file, an unknown profile
"""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import Annotated

import typer
from comfyfetch.cli import app as fetch_app

app = typer.Typer(
    name="comfyctl",
    help=__doc__,
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
    # A crash must not print local variables: they hold tokens. Set explicitly,
    # so it holds on any Typer version the dependency floor allows.
    pretty_exceptions_show_locals=False,
)

# The group IS comfyfetch's app, so `comfyctl fetch <verb>` and `comfyfetch <verb>`
# cannot disagree about flags, output or exit codes.
app.add_typer(fetch_app, name="fetch")

RELAY_UNAVAILABLE = (
    "comfyctl relay is not available in this build: the comfyrelay package is not "
    "installed. comfyrelay ships as the mcp image (ghcr.io/pixeloven/comfyui/mcp), not as a "
    "wheel; from the source tree, run `uv run comfyctl relay …` under services/."
)


def _relay_unavailable() -> None:
    typer.echo(RELAY_UNAVAILABLE, err=True)
    raise typer.Exit(2)


# `relay` mounts comfyrelay's app when that package is installed, and it is
# deliberately NOT a dependency: the released comfyctl wheel must not name a
# package no release ships, which an installer would then look up on PyPI.
# Without it, `relay` is a hidden command that says why, so `comfyctl --help`
# is unchanged and `comfyctl relay …` explains itself rather than reporting
# "No such command". Installed means installed distribution metadata, not
# importable: any directory named comfyrelay on sys.path (a checkout's
# services/, say) imports as an empty namespace package, which find_spec
# reports as present. And not try/except ImportError: a comfyrelay that is
# installed but broken must fail loudly, not look absent.
def _relay_installed() -> bool:
    try:
        importlib.metadata.distribution("comfyrelay")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


if _relay_installed():
    app.add_typer(importlib.import_module("comfyrelay.cli").app, name="relay")
else:
    app.command(
        "relay",
        hidden=True,
        add_help_option=False,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )(_relay_unavailable)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("comfyctl"))
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """comfyctl — one command for ComfyUI-Docker's tooling."""


def main() -> None:
    app()


if __name__ == "__main__":
    main()
