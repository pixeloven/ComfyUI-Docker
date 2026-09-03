"""comfyfetch — resolve, verify and materialise ComfyUI model locks.

Typer, matching comfy-cli and Harmony's `hmy` rather than inventing a third
convention. Deliberately NOT named `comfy`, `comfy-cli` or `comfycli`: comfy-cli
owns those and shadowing them on a user's PATH would be hostile.

One tool, three verbs, and the same behaviour whether it is driven by a person,
a Kubernetes Job, or an agent:

    comfyfetch resolve comfy.yaml > comfy-lock.yaml
    comfyfetch fetch comfy-lock.yaml /workspace --apply
    comfyfetch check comfy.yaml comfy-lock.yaml

EXIT CODES are part of the interface, because automation reads them:

    0  did what was asked
    1  a real failure -- a source did not resolve, a hash did not match,
       a lock and its manifest disagree
    2  the request itself was wrong -- missing file, unknown profile,
       incompatible flags

Human output goes to stderr; stdout carries the artifact, so redirecting it into
a lock file stays correct.
"""

from __future__ import annotations

import importlib.metadata
import pathlib
from typing import Annotated

import typer

from . import check as check_mod
from . import fetch as fetch_mod
from . import lockfile
from . import profiles as profiles_mod
from . import resolve as resolve_mod
from .output import Mode, Out

app = typer.Typer(
    name="comfyfetch",
    help=__doc__,
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

OutputOpt = Annotated[Mode, typer.Option(
    "--output", "-o",
    help="auto: colour at a terminal, plain when piped. json: machine-readable.")]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("comfyfetch"))
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[bool, typer.Option(
        "--version", callback=_version_callback, is_eager=True,
        help="Show the version and exit.")] = False,
) -> None:
    """comfyfetch — resolve, verify and materialise ComfyUI model locks."""


def _load(path: pathlib.Path, what: str) -> dict:
    if not path.is_file():
        typer.echo(f"no such {what}: {path}", err=True)
        raise typer.Exit(2)
    return lockfile.load(path)


@app.command()
def resolve(
    manifest: Annotated[pathlib.Path, typer.Argument(help="comfy.yaml")],
    profile: Annotated[str | None, typer.Option(help="Resolve only this profile.")] = None,
    from_lock: Annotated[pathlib.Path | None, typer.Option(
        "--from-lock",
        help="Select from an existing lock instead of resolving. Requires --profile.")] = None,
    output: OutputOpt = Mode.auto,
) -> None:
    """Manifest → lock. Talks to the network.

    NOT idempotent across time, deliberately: re-resolving a moving `revision:`
    after upstream advances is supposed to produce a new commit and a new hash.
    That is why CI never re-resolves as a drift check — use `check` instead.
    """
    out = Out(output)
    doc = _load(manifest, "manifest")

    if from_lock is not None:
        if profile is None:
            typer.echo("--from-lock needs --profile: without one it would copy "
                       "the lock verbatim", err=True)
            raise typer.Exit(2)
        parent = _load(from_lock, "lock")
        try:
            auth, models = resolve_mod.from_lock(doc, profile, parent)
        except (resolve_mod.Unresolved, profiles_mod.ProfileError) as exc:
            out.problem(str(exc))
            raise typer.Exit(1) from exc
        out.note(f"profile [bold]{profile}[/bold] selects {len(models)} entries "
                 f"from {from_lock}")
        if out.is_json:
            out.result("", {"profile": profile, "entries": len(models), "models": models})
        else:
            typer.echo(lockfile.dump(auth, models), nl=False)
        return

    try:
        declared = resolve_mod.declared_count(doc, profile)
        models, failures = resolve_mod.resolve_all(
            doc, profile,
            on_resolved=lambda cap, name, err: (
                out.problem(f"  UNRESOLVED  {err}") if err
                else out.note(f"resolved [dim]{cap}[/dim]: {name}")))
    except profiles_mod.ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if failures:
        # No lock is written. A lock that looks complete but is short is worse
        # than none, and every failure is reported in this one pass so finding
        # N broken sources does not cost N passes over the network.
        out.problem(f"\n{len(failures)} of {declared} sources did not resolve:")
        for f in failures:
            out.problem(f"  {f}")
        out.problem("\nNo lock written. Fix the manifest and re-run.")
        if out.is_json:
            out.result("", {"resolved": len(models), "declared": declared,
                            "failures": failures, "lock_written": False})
        raise typer.Exit(1)

    if out.is_json:
        out.result("", {"resolved": len(models), "declared": declared,
                        "failures": [], "lock_written": True, "models": models})
    else:
        typer.echo(lockfile.dump(doc.get("auth"), models), nl=False)


@app.command()
def fetch(
    lock: Annotated[pathlib.Path, typer.Argument(help="comfy-lock.yaml")],
    root: Annotated[pathlib.Path, typer.Argument(
        help="ComfyUI ROOT, not the models dir: lock paths begin `models/`.")],
    apply: Annotated[bool, typer.Option(
        "--apply", help="Actually download. Without it nothing is written.")] = False,
    output: OutputOpt = Mode.auto,
) -> None:
    """Lock → disk, verifying every file.

    A wrong-but-plausible model file is worse than a missing one: a missing file
    fails loudly at load, a wrong one renders subtly wrong images forever. An
    entry with no SHA256 is refused rather than fetched unverified.
    """
    out = Out(output)
    if not lock.is_file():
        typer.echo(f"no such lock: {lock}", err=True)
        raise typer.Exit(2)
    # Per-file progress on STDERR. A 25 GB fetch that prints nothing until it
    # finishes is indistinguishable from a hung one -- which is exactly how the
    # first real in-cluster run looked for its first several minutes.
    report = fetch_mod.run(lock, root, dry_run=not apply,
                           progress=None if out.is_json else out.note)
    for line in report.lines:
        out.problem(line)
    out.result(report.render(dry_run=not apply), {
        "present": report.present, "fetched": report.fetched,
        "skipped": report.skipped, "failed": report.failed,
        "would_fetch": report.would, "bytes_written": report.bytes,
        "dry_run": not apply, "problems": report.lines,
    })
    if report.failed:
        raise typer.Exit(1)


@app.command()
def check(
    manifest: Annotated[pathlib.Path, typer.Argument(help="comfy.yaml")],
    lock: Annotated[pathlib.Path, typer.Argument(help="comfy-lock.yaml")],
    profile: Annotated[str | None, typer.Option(
        help="Check a profile's lock against only that profile's capabilities.")] = None,
    output: OutputOpt = Mode.auto,
) -> None:
    """Manifest and lock agree. Offline.

    Deliberately not "re-resolve and diff": a moving `revision:` is supposed to
    advance, so that gate would fail for the one reason that is not a mistake,
    and would need network access to do it.
    """
    out = Out(output)
    doc, lock_doc = _load(manifest, "manifest"), _load(lock, "lock")
    try:
        problems, declared, locked = check_mod.check(doc, lock_doc, profile)
    except profiles_mod.ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    n_profiles = len(doc.get("profiles") or {})
    human = (f"declared: {declared}\nlocked:   {locked}\n"
             + "".join(f"  {p}\n" for p in problems)
             + ("" if problems else
                f"manifest and lock agree; {n_profiles} profiles valid"))
    out.result(human, {"declared": declared, "locked": locked,
                       "problems": problems, "ok": not problems})
    if problems:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
