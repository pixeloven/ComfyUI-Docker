"""Resolve, verify and materialise ComfyUI model locks.

Typer, matching comfy-cli and Harmony's `hmy` rather than inventing a third
convention. This app has no console script of its own: `comfyctl fetch` mounts
it as a group (services/comfyctl), so there is one command and one behaviour.

Five verbs, and the same behaviour whether they are driven by a person, a
Kubernetes Job, or an agent:

    comfyctl fetch build models/ -O comfy.yaml
    comfyctl fetch facts models/ comfy-lock.yaml --store /workspace
    comfyctl fetch resolve comfy.yaml > comfy-lock.yaml
    comfyctl fetch fetch comfy-lock.yaml /workspace --apply
    comfyctl fetch check comfy.yaml comfy-lock.yaml

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
from typing import Annotated, Any, NoReturn

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
    name="fetch",
    help=__doc__,
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
    # A crash must not print local variables: they hold tokens. Set explicitly,
    # so it holds on any Typer version the dependency floor allows.
    pretty_exceptions_show_locals=False,
)

OutputOpt = Annotated[Mode, typer.Option(
    "--output", "-o",
    help="auto: colour at a terminal, plain when piped. json: machine-readable.")]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("comfyctl"))
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[bool, typer.Option(
        "--version", callback=_version_callback, is_eager=True,
        help="Show the version and exit.")] = False,
) -> None:
    """comfyctl fetch — resolve, verify and materialise ComfyUI model locks."""


def _usage(out: Out, message: str) -> NoReturn:
    """A wrong request: exit 2, the reason on stderr.

    Under -o json stdout gets a JSON object as well, so a machine consumer
    always has a result to parse, never a bare exit code (#152).
    """
    typer.echo(message, err=True)
    if out.is_json:
        out.result("", {"problems": [message], "ok": False})
    raise typer.Exit(2)


def _failed(out: Out, message: str, **machine: Any) -> NoReturn:
    """A real failure: exit 1, the reason on stderr.

    Under -o json stdout gets `machine` plus `problems` and `ok: false`. These
    paths once called `out.problem()` and exited, which under json wrote zero
    bytes to either stream (#152).
    """
    out.problem(message)
    if out.is_json:
        out.result("", {**machine, "problems": [message], "ok": False})
    raise typer.Exit(1)


def _reasons(out: Out, problems: list[str]) -> None:
    """Under json the human text is not printed, so a failure's reasons go to
    stderr here: the result is on stdout, the reason on stderr, in every mode."""
    if out.is_json:
        for p in problems:
            out.problem(p)


def _load(path: pathlib.Path, what: str, out: Out) -> dict:
    """A YAML mapping, or exit: 2 if the file is missing, 1 if it is not YAML
    or not a mapping. Either way never a traceback with nothing on stdout."""
    if not path.is_file():
        _usage(out, f"no such {what}: {path}")
    try:
        doc = lockfile.load(path)
    except (yaml.YAMLError, ValueError) as exc:
        _failed(out, f"{what} {path} is not readable YAML: {exc}")
    if not isinstance(doc, dict):
        _failed(out, f"{what} {path} is not a YAML mapping")
    return doc


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
    doc = _load(manifest, "manifest", out)

    if from_lock is not None:
        if profile is None:
            _usage(out, "--from-lock needs --profile: without one it would copy "
                        "the lock verbatim")
        parent = _load(from_lock, "lock", out)
        try:
            auth, models = resolve_mod.from_lock(doc, profile, parent)
        except profiles_mod.ProfileError as exc:
            # An unknown profile is a wrong REQUEST, as it is without
            # --from-lock: exit 2, not 1 (#152).
            _usage(out, str(exc))
        except resolve_mod.Unresolved as exc:
            _failed(out, str(exc), profile=profile, entries=0)
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
        _usage(out, str(exc))

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
                            "failures": failures, "lock_written": False,
                            "problems": failures, "ok": False})
        raise typer.Exit(1)

    if out.is_json:
        out.result("", {"resolved": len(models), "declared": declared,
                        "failures": [], "lock_written": True, "models": models,
                        "problems": [], "ok": True})
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
        _usage(out, f"no such lock: {lock}")

    # #67 asked for this in `fetch` as well as `check`, and the reason is
    # sharper here: fetch WRITES. A malformed lock puts files in the wrong
    # place, or none at all, after the network has already been used.
    lock_problems = schema_mod.validate(_load(lock, "lock", out), "comfy-lock")
    if lock_problems:
        _reasons(out, lock_problems)
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
        "dry_run": not apply, "problems": report.lines, "ok": not report.failed,
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
    subset_only: Annotated[bool, typer.Option(
        "--subset-only",
        help="With --parent: the lock may be NARROWER than the manifest (or "
             "--profile). A declared file it lacks is reported as narrowed, "
             "not NOT LOCKED; a file it holds that is not declared still fails.")] = False,
    output: OutputOpt = Mode.auto,
) -> None:
    """Manifest and lock agree. Offline.

    Deliberately not "re-resolve and diff": a moving `revision:` is supposed to
    advance, so that gate would fail for the one reason that is not a mistake,
    and would need network access to do it.
    """
    out = Out(output)
    if subset_only and parent is None:
        # "A subset of what" is undefined without one (#157).
        _usage(out, "--subset-only needs --parent: it asserts a subset of that lock")
    doc, lock_doc = _load(manifest, "manifest", out), _load(lock, "lock", out)
    # Present in every --subset-only result that exits 0 or 1, so its shape
    # does not depend on how far the check got. An exit 2 (a bad request) has
    # the plain {problems, ok} shape.
    extra: dict[str, Any] = {"narrowed": None} if subset_only else {}

    # FORMAT BEFORE CONSISTENCY. A manifest with `instal:` for `install:` is
    # perfectly consistent with a lock that therefore contains nothing -- so
    # checking agreement first reports a confusing symptom of a plain typo.
    #
    # EVERY failure path goes through _fail, which emits the SAME shape as the
    # success path. Raising here directly once produced exit 1 with zero bytes
    # on either stream: a machine consumer got a failure with no reason
    # attached (#152).
    def _fail(problems: list[str], headline: str) -> None:
        _reasons(out, problems)
        human = headline + "\n" + "".join(f"  {p}\n" for p in problems)
        out.result(human, {"declared": None, "locked": None,
                           "problems": problems, "ok": False, **extra})
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
        parent_doc = _load(parent, "parent lock", out)
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
        _usage(out, str(exc))

    n_profiles = len(doc.get("profiles") or {})
    verdict = f"manifest and lock agree; {n_profiles} profiles valid"
    if subset_only:
        # Only the one-sided half of agreement: NOT DECLARED still fails, since
        # a derived lock must not hold what the manifest does not declare (#157).
        narrowed = [p.removeprefix("NOT LOCKED").strip()
                    for p in problems if p.startswith("NOT LOCKED")]
        problems = [p for p in problems if not p.startswith("NOT LOCKED")]
        extra = {"narrowed": narrowed}
        verdict = (f"the lock declares nothing outside the manifest; "
                   f"{len(narrowed)} declared file(s) narrowed out")
    human = (f"declared: {declared}\nlocked:   {locked}\n"
             + "".join(f"  narrowed     {p}\n" for p in extra.get("narrowed") or [])
             + "".join(f"  {p}\n" for p in problems)
             + ("" if problems else verdict))
    _reasons(out, problems)
    out.result(human, {"declared": declared, "locked": locked,
                       "problems": problems, "ok": not problems, **extra})
    if problems:
        raise typer.Exit(1)


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
        _usage(o, f"no such directory: {sources}")
    if check and out is None:
        _usage(o, "--check needs --out: there is nothing to compare stdout against")

    head = ""
    if header is not None:
        if not header.is_file():
            _usage(o, f"no such header file: {header}")
        head = header.read_text()

    try:
        rendered, counts = build_mod.render(sources, header=head)
    except build_mod.BuildError as exc:
        _failed(o, str(exc))

    summary = (f"{counts['groups']} groups, {counts['profiles']} profiles, "
               f"{counts['capabilities']} capabilities")

    if check:
        if not out.is_file():
            _failed(o, f"{out} does not exist", stale=True, **counts)
        if out.read_text() != rendered:
            _failed(o, f"{out} is STALE against {sources} -- re-run without --check",
                    stale=True, **counts)
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
    lock: Annotated[pathlib.Path | None, typer.Argument(
        help="comfy-lock.yaml, for content hashes. Not with --check.")] = None,
    store: Annotated[pathlib.Path | None, typer.Option(
        help="ComfyUI root. Safetensors headers are read from here.")] = None,
    headers_file: Annotated[pathlib.Path | None, typer.Option(
        "--headers",
        help="Pre-extracted headers as JSON ({install path: __metadata__}, each "
             "path relative to the ComfyUI root, e.g. models/loras/x.safetensors). "
             "Use when the store is not reachable from here -- a Kubernetes store "
             "lives inside the cluster while the sources are in a checkout "
             "outside it.")] = None,
    token: Annotated[str | None, typer.Option(
        envvar="CIVITAI_TOKEN",
        help="Optional. Public by-hash lookups do NOT need one.")] = None,
    generated: Annotated[str | None, typer.Option(
        help="Date stamped into each sidecar. Defaults to today; pass a fixed "
             "value to make output reproducible.")] = None,
    check: Annotated[bool, typer.Option(
        "--check",
        help="Offline, for CI: exit 1 if a committed sidecar has no sibling "
             "lineage, or names a file its lineage does not declare. Reads "
             "SOURCES only: no lock, store or network.")] = False,
    output: OutputOpt = Mode.auto,
) -> None:
    """Measure what each model IS, and write a sidecar per lineage. NETWORK.

    Writes `<lineage>.facts.yaml` beside each source file, recording what the
    trainer put in the safetensors header and what the publisher claims for the
    file's CONTENT HASH. Where those disagree, the disagreement is the point.
    Files are keyed by install path, because basenames repeat.

    Needs the store on disk AND network, so it cannot run in CI -- the same
    contract as `resolve`. `--check` is the offline freshness gate CI runs.
    """
    import time as _time

    out = Out(output)
    if not sources.is_dir():
        _usage(out, f"no such directory: {sources}")

    if check:
        # The same idea as `build --check`: a committed generated artifact,
        # and an offline staleness gate for it (#155).
        if lock is not None or store is not None or headers_file is not None:
            _usage(out, "--check reads SOURCES only: it takes no lock, --store or --headers")
        problems, sidecars = facts_mod.stale(sources)
        _reasons(out, problems)
        human = ("".join(f"  {p}\n" for p in problems)
                 + (f"{len(problems)} problem(s) in {sidecars} facts sidecars" if problems
                    else f"{sidecars} facts sidecars match their lineages"))
        out.result(human, {"sidecars": sidecars, "problems": problems, "ok": not problems})
        if problems:
            raise typer.Exit(1)
        return

    if lock is None:
        _usage(out, "facts needs LOCK, for content hashes (--check needs none)")
    if (store is None) == (headers_file is None):
        _usage(out, "pass exactly one of --store or --headers")
    if store is not None and not (store / "models").is_dir():
        # The ComfyUI ROOT, as `fetch` takes: install paths begin `models/`. A
        # models directory here matched nothing and wrote empty sidecars.
        _usage(out, f"--store takes the ComfyUI root, the directory holding models/: "
                    f"{store / 'models'} is not a directory")
    if headers_file is not None and not headers_file.is_file():
        _usage(out, f"no such headers file: {headers_file}")
    doc = _load(lock, "lock", out)

    lineages: list[tuple[pathlib.Path, dict]] = []
    declared: set[str] = set()
    for path in sorted(sources.rglob("*.yaml")):
        if path.name in facts_mod.RESERVED or path.name.endswith(".facts.yaml"):
            continue
        try:
            lineage = yaml.safe_load(path.read_text()) or {}
            declared.update(facts_mod.declared(lineage))
        except (yaml.YAMLError, ValueError, KeyError, TypeError, AttributeError) as exc:
            _failed(out, f"{path} is not a lineage source: {type(exc).__name__}: {exc}")
        lineages.append((path, lineage))

    # Every join is by INSTALL PATH, never basename. Basenames repeat
    # (`diffusion_pytorch_model.safetensors` is HuggingFace's default), and a
    # last-wins dict keyed by name handed one file's header and hash to the
    # other (#153). Every path of an entry holds the same bytes, so one hash.
    shas = {
        p["path"]: h["hash"]
        for m in doc.get("models") or []
        for h in m.get("hashes") or []
        if h.get("type") == "SHA256"
        for p in m.get("paths") or []
    }
    if headers_file is not None:
        try:
            headers = json.loads(headers_file.read_text())
        except ValueError as exc:
            _failed(out, f"--headers {headers_file} is not readable JSON: {exc}")
        if not isinstance(headers, dict):
            _usage(out, "--headers must be a JSON object, {install path: __metadata__}, "
                        f"not a {type(headers).__name__}")
        # Every declared path starts `models/` (the schema's `install` pattern),
        # so a key that does not can never match.
        bad = sorted(k for k in headers if not k.startswith("models/"))
        if bad:
            _usage(out, "--headers keys must be install paths relative to the ComfyUI "
                        f"root, starting models/: {', '.join(bad[:3])}")
    else:
        headers = {
            p.relative_to(store).as_posix(): facts_mod.safetensors_header(p)
            for p in store.rglob("*.safetensors")
        }
        wanted = {p for p in declared if p.endswith(".safetensors")}
        if wanted and not wanted & headers.keys():
            _usage(out, f"no declared .safetensors file is under {store}: --store takes "
                        f"the ComfyUI root, the directory holding models/")
    out.note(f"{len(shas)} hashes from the lock, {len(headers)} safetensors headers read")

    stamp = generated or _time.strftime("%Y-%m-%d")
    written = 0
    for path, lineage in lineages:
        rendered = facts_mod.render(
            lineage, headers=headers, shas=shas, token=token, generated=stamp)
        if rendered:
            path.with_suffix(".facts.yaml").write_text(rendered)
            written += 1
            out.note(f"  {path.with_suffix('.facts.yaml').name}")
    out.note(f"wrote {written} facts sidecars")
    if out.is_json:
        out.result("", {"sidecars": written})


# LAST, after every @app.command(). Above `build` and `facts` it ran the app
# before they were registered, so `python -m comfyfetch.cli build` said
# "No such command 'build'".
def main() -> None:
    app()


if __name__ == "__main__":
    main()
