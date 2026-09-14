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
    from . import profiles as profiles_mod

    out: list[str] = []
    profiles = doc.get("profiles") or {}
    groups = {g["name"]: g for g in doc.get("models") or []
              if isinstance(g, dict) and "name" in g}

    # PROFILE FAULTS FIRST, AND AS THEMSELVES. Everything below walks profiles
    # to find types, so a profile that cannot expand -- a name that is both a
    # group and a profile, a member that does not exist -- contributes zero
    # types and makes every `requires` look unmet. Reporting that instead of
    # the expansion failure sends the reader after a phantom type problem while
    # the real defect goes unmentioned: the exact "symptom instead of cause"
    # this module exists to avoid.
    profile_faults = profiles_mod.validate_all(doc)
    if profile_faults:
        return profile_faults

    def types_in(names: list[str]) -> set[str]:
        """Types reachable from a capability's profiles, as a UNION.

        PER-PROFILE, not manifest-wide. Collecting every type in the manifest
        makes the check nearly vacuous: a capability whose profiles resolve
        only upscalers would satisfy `requires: [diffusion_models]` because
        some unrelated lineage declares one. The union is also why `profiles`
        is plural -- an add-on profile resolves no checkpoint by design, so the
        contract holds over the set, not each member.
        """
        found: set[str] = set()
        for name in names:
            # Cannot raise: validate_all above returned clean, so every
            # profile in this manifest expands.
            members = profiles_mod.expand(doc, name) if name in profiles else [name]
            for member in members:
                for f in (groups.get(member) or {}).get("files") or []:
                    if isinstance(f, dict) and f.get("type"):
                        found.add(f["type"])
        return found

    for cap, spec in (doc.get("capabilities") or {}).items():
        if not isinstance(spec, dict):
            continue
        named = spec.get("profiles") or []
        for profile in named:
            if profile not in profiles and profile not in groups:
                out.append(
                    f"capability {cap!r}: names profile {profile!r}, which is "
                    f"neither a profile nor a model group")
        required = spec.get("requires") or []
        if not required:
            out.append(f"capability {cap!r}: declares no `requires` -- a capability "
                       f"with no contract cannot be checked")
        reachable = types_in([p for p in named if p in profiles or p in groups])
        for want in required:
            if want not in reachable:
                out.append(
                    f"capability {cap!r}: requires type {want!r}, which none of its "
                    f"profiles resolve -- the graph would load and not render")
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
    # MEMBERSHIP, not lookup-by-name. Keying the parent by `model` (the
    # filename) is wrong twice: identity in a lock is the install PATH, which is
    # what --from-lock selects on, and the same basename legitimately appears
    # more than once -- `diffusion_pytorch_model.safetensors` is the norm on
    # HuggingFace, and one real consumer already carries two entries called
    # `qwen_3_4b.safetensors` from different repos. A last-wins dict silently
    # compares a child entry against the wrong parent entry and reports drift
    # that does not exist.
    #
    # "Verbatim subset" is exactly `entry in parent_models`, so say that.
    parent_models = parent.get("models") or []
    out: list[str] = []
    for entry in child.get("models") or []:
        if entry in parent_models:
            continue
        where = (entry.get("paths") or [{}])[0].get("path") or entry.get("model") or "?"
        if any(
            (p.get("paths") or [{}])[0].get("path") == where for p in parent_models
        ):
            out.append(
                f"{where}: differs from the parent lock -- --from-lock selects "
                f"verbatim, so a difference means it was re-resolved")
        else:
            out.append(
                f"{where}: not present in the parent lock -- a derived lock "
                f"selects from its parent, it does not add to it")
    return out
