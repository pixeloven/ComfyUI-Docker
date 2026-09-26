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
)

# The group IS comfyfetch's app, so `comfyctl fetch <verb>` and `comfyfetch <verb>`
# cannot disagree about flags, output or exit codes.
app.add_typer(fetch_app, name="fetch")


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
