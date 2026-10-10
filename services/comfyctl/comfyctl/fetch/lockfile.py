"""Reading manifests and writing locks.

A lock's `models[]` entries are byte-for-byte comfy-cli's documented shape —
`model`, `url`, `paths`, `hashes`, `type`. The only addition anywhere is a
top-level `auth` map, which upstream has no equivalent for and which never
appears inside a model entry.
"""

from __future__ import annotations

import io
import pathlib
from typing import Any

import yaml


def load(path: pathlib.Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def install_path(entry: dict) -> str:
    """Where a manifest entry lands, derived from the manifest ALONE.

    `as` wins; otherwise the basename of `file`. The schema requires `as` for
    civitai sources precisely so this stays computable offline — which is what
    lets check-lock run without network.
    """
    name = entry.get("as") or pathlib.PurePosixPath(entry.get("file") or "").name
    return f"{entry['install']}{name}"


def _declaration(entry: dict) -> dict:
    """What a manifest entry says about its file, with the defaults filled in.

    `x-` keys are consumer metadata. A missing `revision` is `main`, an `as`
    equal to `file`'s basename names nothing new, and a sha256 is the same
    hash in either case. Without this, two spellings of one file conflict.
    """
    decl = {k: v for k, v in entry.items() if not k.startswith("x-")}
    decl.setdefault("revision", "main")
    if decl.get("as") == pathlib.PurePosixPath(decl.get("file") or "").name:
        decl.pop("as")
    if isinstance(decl.get("sha256"), str):
        decl["sha256"] = decl["sha256"].lower()
    return decl


def conflicts(groups: list[dict]) -> dict[str, str]:
    """Install paths that file entries declare DIFFERENTLY -> what differs.

    The same file declared identically in two groups (a VAE shared by a base
    and an add-on) is one install and one lock entry. Two different
    declarations for one path are two files fighting over it: the last fetched
    wins, and every fetch re-downloads both. Each message names the groups
    that differ from the path's first declaration, and the keys that do.
    """
    first: dict[str, tuple[str, dict]] = {}
    differ: dict[str, tuple[list[str], set[str]]] = {}
    for group in groups:
        for entry in group["files"]:
            path, decl = install_path(entry), _declaration(entry)
            if path not in first:
                first[path] = (group["name"], decl)
                continue
            name0, decl0 = first[path]
            if decl == decl0:
                continue
            names, keys = differ.setdefault(path, ([name0], set()))
            if group["name"] not in names:
                names.append(group["name"])
            keys.update(k for k in decl.keys() | decl0.keys() if decl.get(k) != decl0.get(k))
    out = {}
    for path, (names, keys) in sorted(differ.items()):
        who = " and ".join(repr(n) for n in names) if len(names) > 1 \
            else f"{names[0]!r} twice"
        what = " and ".join(sorted(keys))
        out[path] = (f"{path}: declared by {who} with a different {what}; "
                     f"one install path can hold only one file")
    return out


def duplicate_paths(lock: dict) -> list[str]:
    """Install paths a lock lists more than once. A lock has one entry per file."""
    counts: dict[str, int] = {}
    for m in lock.get("models") or []:
        if (p := lock_path(m)) is not None:
            counts[p] = counts.get(p, 0) + 1
    return [p for p, n in counts.items() if n > 1]


def sha256_of(model: dict) -> str | None:
    for h in model.get("hashes") or []:
        if h.get("type") == "SHA256":
            return str(h["hash"]).lower()
    return None


def lock_path(model: dict) -> str | None:
    paths = model.get("paths") or []
    return paths[0]["path"] if paths else None


class _Dumper(yaml.SafeDumper):
    """PyYAML puts sequence items at the parent's indent level; every YAML file
    in these repos indents them under their key."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data: Any) -> bool:
        # A shared dict must never become an `&id001` anchor and `*id001`
        # alias: a lock is read by tools that aren't PyYAML.
        return True


def dump(auth: dict | None, models: list[dict]) -> str:
    """Render a lock document.

    Sorted by install path so the output is byte-stable and a drift gate can
    diff it.
    """
    out = io.StringIO()
    if auth:
        yaml.dump({"auth": auth}, out, Dumper=_Dumper, sort_keys=False,
                  default_flow_style=False, width=10_000)
    ordered = sorted(models, key=lambda m: lock_path(m) or "")
    yaml.dump({"models": ordered}, out, Dumper=_Dumper, sort_keys=False,
              default_flow_style=False, width=10_000)
    return out.getvalue()
