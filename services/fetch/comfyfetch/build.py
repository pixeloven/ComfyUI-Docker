"""Manifest assembly from per-lineage source files.

A single comfy.yaml does not scale. At ~1,400 lines every model family
conflicts with every other on edit, and there is no way to ship one family
without the rest. `build` assembles the manifest from one file per lineage.

The generated manifest stays COMMITTED rather than gitignored: comfyfetch,
CI and any policy gate read it directly, and a build step between `git clone`
and `comfyfetch check` is a step that gets skipped.

WHAT A SOURCE FILE LOOKS LIKE

    family: flux            # optional, for the reader
    lineage: flux2          # optional, for the reader
    summary: >-             # optional, PRESERVED into the artifact
      Free text. The judgement a reader needs and the file list cannot
      express -- which generations are interchangeable, what a deviation from
      upstream cost, why a variant is absent.
    groups:
      - name: flux2-diffusion
        files: [...]

`summary:` is the reason this verb is not just `cat`. A summary that exists
only in the source file is invisible where the manifest is actually consumed,
so it is re-attached as a comment above that lineage's first group.

DIRECTORY LAYOUT IS THE CALLER'S. `build` walks a tree and does not care how it
is split. Splitting it -- shared/ vs custom/, tutorial-aligned vs personal
taste -- is a convention worth having, but it is a directory boundary so the
halves can be separated with `git mv` rather than a re-sort.
"""

from __future__ import annotations

import pathlib

import yaml

from . import profiles as profiles_mod

RESERVED = ("profiles.yaml", "capabilities.yaml", "_meta.yaml")


class BuildError(Exception):
    pass


class _Dumper(yaml.SafeDumper):
    """yamllint requires sequences indented under their key; PyYAML does not.

    safe_dump emits indentless sequences, which yamllint flags as `wrong
    indentation: expected 2 but found 0` on every list item. Overriding
    increase_indent is the documented fix and changes nothing about the parsed
    content.
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def dump(data: object) -> str:
    return yaml.dump(
        data, Dumper=_Dumper, sort_keys=False, width=100, default_flow_style=False
    )


def load_sources(root: pathlib.Path) -> tuple[list[dict], dict[str, str]]:
    """Every group from every lineage file under `root`, plus lineage summaries.

    A duplicate group name is fatal rather than last-wins: two lineages
    declaring the same group is an editing accident, and silently keeping one
    of them drops models nobody asked to drop.
    """
    groups: list[dict] = []
    summaries: dict[str, str] = {}
    seen: dict[str, pathlib.Path] = {}
    for path in sorted(root.rglob("*.yaml")):
        if path.name in RESERVED:
            continue
        doc = yaml.safe_load(path.read_text()) or {}
        for group in doc.get("groups") or []:
            if "name" not in group:
                raise BuildError(f"group without a name in {path}")
            name = group["name"]
            if name in seen:
                raise BuildError(f"duplicate group {name!r} in {path} and {seen[name]}")
            seen[name] = path
            groups.append(group)
            if doc.get("summary"):
                summaries[name] = str(doc["summary"]).strip()
    return groups, summaries


def render(root: pathlib.Path, *, header: str = "") -> tuple[str, dict]:
    """Assemble the manifest text and return it with its parsed counts.

    `_meta.yaml` supplies name/description/auth; profiles.yaml and
    capabilities.yaml are copied through. All three are optional -- a store
    with no profiles is a legitimate store.
    """
    meta_path = root / "_meta.yaml"
    if not meta_path.is_file():
        raise BuildError(f"no _meta.yaml in {root}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    groups, summaries = load_sources(root)
    if not groups:
        raise BuildError(f"no groups found under {root}")

    doc: dict = {}
    for key in ("name", "description", "auth"):
        if key in meta:
            doc[key] = meta[key]
    doc["models"] = groups
    for key, fname in (("profiles", "profiles.yaml"), ("capabilities", "capabilities.yaml")):
        path = root / fname
        if path.is_file():
            doc[key] = yaml.safe_load(path.read_text()) or {}

    # REFUSE A COLLISION BEFORE THE MANIFEST EXISTS, which is why this check is
    # here as well as in expand(). `resolve` WITHOUT --profile never calls
    # expand() at all, so an expand()-only refusal still lets a full resolve
    # accept a colliding manifest. Refusing at assembly time means one never
    # reaches disk.
    clash = profiles_mod.collisions(doc)
    if clash:
        names = ", ".join(repr(c) for c in clash)
        raise BuildError(
            f"{names} is both a model group and a profile -- the group wins, so "
            f"the profile would silently resolve the wrong file set"
        )

    body = dump(doc)

    # Re-attach each lineage's summary above its first group.
    #
    # MATCH THE INDENTED FORM. _Dumper indents sequences under their key, so a
    # group line is "  - name: x", not "- name: x". Matching the unindented form
    # fires on nothing and drops every summary -- which is exactly what happened
    # in the store this verb was extracted from: 13 lineages' worth of
    # judgement, none of it in the artifact, and no error either way. The whole
    # reason `build` is not `cat` failed silently for as long as it existed.
    out: list[str] = []
    emitted: set[str] = set()
    for line in body.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("- name: "):
            indent = line[: len(line) - len(stripped)]
            summary = summaries.get(stripped[len("- name: ") :].strip())
            if summary and summary not in emitted:
                emitted.add(summary)
                out.extend(f"{indent}# {s}".rstrip() + "\n" for s in summary.splitlines())
        out.append(line)

    counts = {
        "groups": len(groups),
        "profiles": len(doc.get("profiles") or {}),
        "capabilities": len(doc.get("capabilities") or {}),
    }
    return header + "".join(out), counts
