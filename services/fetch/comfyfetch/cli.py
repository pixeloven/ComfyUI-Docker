"""comfyfetch — resolve, verify and materialise ComfyUI model locks.

Typer, matching comfy-cli and Harmony's `hmy` rather than inventing a third
convention. Deliberately NOT named `comfy`, `comfy-cli` or `comfycli`: comfy-cli
owns those and shadowing them on a user's PATH would be hostile.

One tool, five verbs, and the same behaviour whether it is driven by a person,
a Kubernetes Job, or an agent:

    comfyfetch build models/ -o comfy.yaml
    comfyfetch facts models/ comfy-lock.yaml --store /workspace/models
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
import json
import pathlib
from typing import Annotated

import typer
import yaml

from . import build as build_mod
from . import check as check_mod
from . import facts as facts_mod
from . import fetch as fetch_mod
from . import lockfile
from . import profiles as profiles_mod
from . import schema as schema_mod
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

    # #67 asked for this in `fetch` as well as `check`, and the reason is
    # sharper here: fetch WRITES. A malformed lock puts files in the wrong
    # place, or none at all, after the network has already been used.
    lock_problems = schema_mod.validate(lockfile.load(lock), "comfy-lock")
    if lock_problems:
        out.result("\n".join(f"  {p}" for p in lock_problems),
                   {"problems": lock_problems, "ok": False})
        raise typer.Exit(1)
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
    parent: Annotated[pathlib.Path | None, typer.Option(
        help="Assert this lock is a verbatim subset of the lock it was derived "
             "from with --from-lock.")] = None,
    output: OutputOpt = Mode.auto,
) -> None:
    """Manifest and lock agree. Offline.

    Deliberately not "re-resolve and diff": a moving `revision:` is supposed to
    advance, so that gate would fail for the one reason that is not a mistake,
    and would need network access to do it.
    """
    out = Out(output)
    doc, lock_doc = _load(manifest, "manifest"), _load(lock, "lock")

    # FORMAT BEFORE CONSISTENCY. A manifest with `instal:` for `install:` is
    # perfectly consistent with a lock that therefore contains nothing -- so
    # checking agreement first reports a confusing symptom of a plain typo.
    #
    # EVERY failure path goes through _fail, which emits the SAME shape as the
    # success path. Out.problem is a deliberate no-op under --output json, so
    # raising here directly produced exit 1 with zero bytes on either stream:
    # a machine consumer got a failure with no reason attached.
    def _fail(problems: list[str], headline: str) -> None:
        human = headline + "\n" + "".join(f"  {p}\n" for p in problems)
        out.result(human, {"declared": None, "locked": None,
                           "problems": problems, "ok": False})
        raise typer.Exit(1)

    problems = schema_mod.validate(doc, "comfy")
    # Semantics only once the STRUCTURE holds. `models: "oops"` otherwise
    # reaches .get() on a string and shows a traceback instead of the schema
    # message -- the opposite of what "format before consistency" is for.
    if not problems:
        problems = schema_mod.validate_semantics(doc)
    problems += [f"lock: {p}" for p in schema_mod.validate(lock_doc, "comfy-lock")]
    if problems:
        _fail(problems, f"{len(problems)} schema problem(s):")

    if parent is not None:
        parent_doc = _load(parent, "parent lock")
        bad_parent = schema_mod.validate(parent_doc, "comfy-lock")
        if bad_parent:
            _fail([f"parent: {p}" for p in bad_parent],
                  f"{len(bad_parent)} problem(s) in the parent lock:")
        drift = schema_mod.subset_problems(lock_doc, parent_doc)
        if drift:
            _fail(drift, f"{len(drift)} entr(ies) differ from {parent}:")
        out.note(f"verbatim subset of {parent}")

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


@app.command()
def build(
    sources: Annotated[pathlib.Path, typer.Argument(
        help="Directory of per-lineage source files.")],
    out: Annotated[pathlib.Path, typer.Option(
        "--out", "-O", help="Where to write the manifest. Default: stdout.")] = None,
    header: Annotated[pathlib.Path | None, typer.Option(
        help="File whose contents are prepended to the manifest, verbatim.")] = None,
    check: Annotated[bool, typer.Option(
        "--check", help="Exit 1 if --out is stale instead of writing it.")] = False,
    output: OutputOpt = Mode.auto,
) -> None:
    """Per-lineage sources → manifest. Offline.

    One file per lineage, because a single manifest does not scale: every
    family conflicts with every other on edit, and there is no way to ship one
    family without the rest.

    `--check` is the CI form. The manifest is committed, so it can go stale
    against its sources, and a stale manifest resolves the WRONG MODELS while
    every other gate stays green -- which is why this is a check rather than a
    build step nobody runs.
    """
    o = Out(output)
    if not sources.is_dir():
        typer.echo(f"no such directory: {sources}", err=True)
        raise typer.Exit(2)
    if check and out is None:
        typer.echo("--check needs --out: there is nothing to compare stdout against",
                   err=True)
        raise typer.Exit(2)

    head = ""
    if header is not None:
        if not header.is_file():
            typer.echo(f"no such header file: {header}", err=True)
            raise typer.Exit(2)
        head = header.read_text()

    try:
        rendered, counts = build_mod.render(sources, header=head)
    except build_mod.BuildError as exc:
        o.problem(str(exc))
        raise typer.Exit(1) from exc

    summary = (f"{counts['groups']} groups, {counts['profiles']} profiles, "
               f"{counts['capabilities']} capabilities")

    if check:
        if not out.is_file():
            o.problem(f"{out} does not exist")
            raise typer.Exit(1)
        if out.read_text() != rendered:
            o.problem(f"{out} is STALE against {sources} -- re-run without --check")
            raise typer.Exit(1)
        o.note(f"{out} up to date ({summary})")
        if o.is_json:
            o.result("", {"stale": False, **counts})
        return

    if out is None:
        typer.echo(rendered, nl=False)
        o.note(summary)
        return
    out.write_text(rendered)
    o.note(f"wrote {out}: {summary}")
    if o.is_json:
        o.result("", {"path": str(out), **counts})


@app.command()
def facts(
    sources: Annotated[pathlib.Path, typer.Argument(
        help="Directory of per-lineage source files -- the same root `build` takes.")],
    lock: Annotated[pathlib.Path, typer.Argument(help="comfy-lock.yaml, for content hashes.")],
    store: Annotated[pathlib.Path | None, typer.Option(
        help="ComfyUI root. Safetensors headers are read from here.")] = None,
    headers_file: Annotated[pathlib.Path | None, typer.Option(
        "--headers",
        help="Pre-extracted headers as JSON ({filename: __metadata__}). Use "
             "when the store is not reachable from here -- a Kubernetes store "
             "lives inside the cluster while the sources are in a checkout "
             "outside it.")] = None,
    token: Annotated[str | None, typer.Option(
        envvar="CIVITAI_TOKEN",
        help="Optional. Public by-hash lookups do NOT need one.")] = None,
    generated: Annotated[str | None, typer.Option(
        help="Date stamped into each sidecar. Defaults to today; pass a fixed "
             "value to make output reproducible.")] = None,
    output: OutputOpt = Mode.auto,
) -> None:
    """Measure what each model IS, and write a sidecar per lineage. NETWORK.

    Writes `<lineage>.facts.yaml` beside each source file, recording what the
    trainer put in the safetensors header and what the publisher claims for the
    file's CONTENT HASH. Where those disagree, the disagreement is the point.

    Needs the store on disk AND network, so it cannot run in CI -- the same
    contract as `resolve`. Enforce freshness offline instead, by comparing each
    sidecar's key set against its sibling lineage.
    """
    import time as _time

    out = Out(output)
    if not sources.is_dir():
        typer.echo(f"no such directory: {sources}", err=True)
        raise typer.Exit(2)
    if (store is None) == (headers_file is None):
        typer.echo("pass exactly one of --store or --headers", err=True)
        raise typer.Exit(2)
    if store is not None and not store.is_dir():
        typer.echo(f"store not readable: {store}", err=True)
        raise typer.Exit(2)
    if headers_file is not None and not headers_file.is_file():
        typer.echo(f"no such headers file: {headers_file}", err=True)
        raise typer.Exit(2)
    doc = _load(lock, "lock")

    shas = {
        m["model"]: h["hash"]
        for m in doc.get("models") or []
        for h in m.get("hashes") or []
        if h.get("type") == "SHA256"
    }
    if headers_file is not None:
        headers = json.loads(headers_file.read_text())
    else:
        headers = {
            p.name: facts_mod.safetensors_header(p)
            for p in store.rglob("*.safetensors")
        }
    out.note(f"{len(shas)} hashes from the lock, {len(headers)} safetensors headers read")

    stamp = generated or _time.strftime("%Y-%m-%d")
    written = 0
    for path in sorted(sources.rglob("*.yaml")):
        if path.name in facts_mod.RESERVED or path.name.endswith(".facts.yaml"):
            continue
        lineage = yaml.safe_load(path.read_text()) or {}
        rendered = facts_mod.render(
            lineage, headers=headers, shas=shas, token=token, generated=stamp)
        if rendered:
            path.with_suffix(".facts.yaml").write_text(rendered)
            written += 1
            out.note(f"  {path.with_suffix('.facts.yaml').name}")
    out.note(f"wrote {written} facts sidecars")
    if out.is_json:
        out.result("", {"sidecars": written})
