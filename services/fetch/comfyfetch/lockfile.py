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
