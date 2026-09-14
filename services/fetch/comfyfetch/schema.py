"""The definition of a valid manifest, owned by the tool that reads it.

A consumer wanting schema validation had to run `check-jsonschema` against a
path INSIDE a checkout of this repo -- which was the only reason some of them
kept a checkout. The tool owns the format, so it owns saying what conforms.

TWO LAYERS, deliberately separate:

  * `validate()`  -- STRUCTURE, from the bundled JSON Schema. Catches `instal:`
    for `install:`, which otherwise installs nothing and reports success.
  * `validate_semantics()` -- relationships the schema cannot express: a
    capability naming a profile that does not exist, or requiring a `type:` no
    file in the manifest declares.

EXTENSIONS ARE NAMED, NOT ALLOWED. `additionalProperties: false` is what makes
a typo an error, so it stays -- and `^x-` keys are permitted alongside it. That
is the convention OpenAPI settled on, and it keeps "unknown bare key" a
failure. comfyfetch ignores `x-` content entirely; it exists so a consumer can
carry its own metadata in the file it already maintains.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import jsonschema


def load(name: str) -> dict[str, Any]:
    """A bundled schema by name: `comfy` or `comfy-lock`."""
    text = (resources.files("comfyfetch.schemas") / f"{name}.schema.json").read_text()
    return json.loads(text)


def validate(doc: dict, name: str) -> list[str]:
    """Structural problems, best-first. Empty means it conforms."""
    validator = jsonschema.Draft202012Validator(load(name))
    out = []
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in error.path) or "(root)"
        out.append(f"{where}: {error.message}")
    return out


def validate_semantics(doc: dict) -> list[str]:
    """Relationships a JSON Schema cannot express.

    Structural only -- it never asks whether a file EXISTS, which needs the
    network. That separation is what lets this run in CI.
    """
    out: list[str] = []
    profiles = doc.get("profiles") or {}
    groups = {g["name"] for g in doc.get("models") or [] if isinstance(g, dict) and "name" in g}
    declared_types = {
        f.get("type")
        for g in doc.get("models") or []
        for f in (g.get("files") or [])
        if f.get("type")
    }

    for cap, spec in (doc.get("capabilities") or {}).items():
        if not isinstance(spec, dict):
            continue
        for profile in spec.get("profiles") or []:
            if profile not in profiles and profile not in groups:
                out.append(
                    f"capability {cap!r}: names profile {profile!r}, which is "
                    f"neither a profile nor a model group")
        required = spec.get("requires") or []
        if not required:
            out.append(f"capability {cap!r}: declares no `requires` -- a capability "
                       f"with no contract cannot be checked")
        for want in required:
            if want not in declared_types:
                out.append(
                    f"capability {cap!r}: requires type {want!r}, which no file in "
                    f"this manifest declares -- the graph would load and not render")
    return out


def subset_problems(child: dict, parent: dict) -> list[str]:
    """A derived lock must be a VERBATIM subset of the lock it came from.

    `resolve --from-lock` SELECTS rather than re-resolves, so no hash in a
    profile lock can legitimately differ from the one in its parent. Resolving
    each profile independently instead lets locks generated minutes apart pin
    different upstream commits -- and nothing downstream would ever notice,
    because each lock is internally consistent and each passes `check`.

    This is a format invariant, which is why it lives here rather than being
    reimplemented by every consumer that derives locks.
    """
    by_name = {m["model"]: m for m in parent.get("models") or []}
    out: list[str] = []
    for entry in child.get("models") or []:
        name = entry.get("model")
        origin = by_name.get(name)
        if origin is None:
            out.append(f"{name}: not present in the parent lock -- a derived lock "
                       f"selects from its parent, it does not add to it")
            continue
        if entry != origin:
            out.append(f"{name}: differs from the parent lock -- --from-lock selects "
                       f"verbatim, so a difference means it was re-resolved")
    return out
