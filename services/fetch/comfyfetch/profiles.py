"""Profile expansion.

A profile names capabilities or other profiles, so profiles compose by SET
UNION — the "sometimes I want both" case without inheritance, resolution order,
overrides or diamonds. None of that machinery is needed because the fetch is
content-addressed: a model shared between profiles is declared once and
installed once.
"""

from __future__ import annotations


class ProfileError(Exception):
    pass


def expand(manifest: dict, name: str) -> list[str]:
    """Capability names a profile selects, expanded transitively.

    Bounded, not merely self-reference-checked: `a -> b -> a` is the same defect
    one step further out, and a self-reference check would miss it.
    """
    profiles = manifest.get("profiles") or {}
    if name not in profiles:
        raise ProfileError(f"no such profile: {name}")

    known = {m["name"] for m in manifest.get("models") or []}
    selected: list[str] = []
    frontier = [name]
    for _ in range(32):
        if not frontier:
            return selected
        nxt: list[str] = []
        for member in frontier:
            if member in known:
                if member not in selected:
                    selected.append(member)
            elif member in profiles:
                nxt.extend(profiles[member])
            else:
                raise ProfileError(
                    f"profile member is neither a model nor a profile: {member}"
                )
        frontier = nxt
    raise ProfileError(f"profile {name} does not settle after 32 rounds: cycle")


def validate_all(manifest: dict) -> list[str]:
    """Every profile's members resolve and every expansion terminates.

    Checked here rather than at resolve time: a typo in a profile member is
    otherwise only discovered when someone resolves THAT profile, which may be
    never.
    """
    problems: list[str] = []
    for name in (manifest.get("profiles") or {}):
        try:
            expand(manifest, name)
        except ProfileError as exc:
            problems.append(f"{name}: {exc}")
    return problems
