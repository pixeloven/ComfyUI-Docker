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



def collisions(manifest: dict) -> list[str]:
    """Names that are BOTH a model group and a profile.

    comfyfetch resolves both out of one namespace and `expand()` tests
    `member in known` before `member in profiles`, so the group always wins. A
    profile named after a group therefore resolves the GROUP, at every level --
    and the resulting lock is self-consistent, correctly hashed and passes
    `check`, because every one of those paths goes through this same function.

    Observed downstream before this refusal existed: a profile resolved 2 files
    instead of 13, and another 3 instead of 15. No error either time; the only
    symptom was a file count nobody was watching.
    """
    groups = {m["name"] for m in manifest.get("models") or [] if isinstance(m, dict) and "name" in m}
    return sorted(groups & set(manifest.get("profiles") or {}))


def _refuse_collisions(manifest: dict) -> None:
    clash = collisions(manifest)
    if clash:
        names = ", ".join(repr(c) for c in clash)
        raise ProfileError(
            f"{names} is both a model group and a profile -- the group wins, so "
            f"the profile silently resolves the wrong file set"
        )

def expand(manifest: dict, name: str) -> list[str]:
    """Capability names a profile selects, expanded transitively.

    Bounded, not merely self-reference-checked: `a -> b -> a` is the same defect
    one step further out, and a self-reference check would miss it.
    """
    _refuse_collisions(manifest)
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
    # A collision is a property of the MANIFEST, so it is computed once here.
    # Letting expand() raise inside the loop would turn one defect into N
    # identical problems, one per profile.
    try:
        _refuse_collisions(manifest)
    except ProfileError as exc:
        return [str(exc)]
    for name in (manifest.get("profiles") or {}):
        try:
            expand(manifest, name)
        except ProfileError as exc:
            problems.append(f"{name}: {exc}")
    return problems
