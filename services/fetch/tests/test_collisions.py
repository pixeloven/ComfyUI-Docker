"""A group and a profile must never share a name.

comfyfetch resolves both out of ONE namespace and the group wins, because
`expand()` tests `member in known` before `member in profiles`. So a profile
named after a group resolves the GROUP -- silently, with a self-consistent lock,
correct hashes and a passing `check`.

Cost before this refusal existed, in one downstream store: `flux1-edit` resolved
2 files instead of 13, and `utility-restoration` 3 instead of 15. Neither
produced an error; the only symptom was a file count nobody was watching.
"""

import pathlib

import pytest
import yaml
from comfyfetch import build, profiles
from typer.testing import CliRunner

from comfyfetch.cli import app

runner = CliRunner()

COLLIDING = {
    "models": [{"name": "shared-vae", "files": [{"file": "a.safetensors"}]}],
    "profiles": {
        "shared-vae": ["shared-vae"],          # profile named after the group
        "downstream": ["shared-vae"],          # and one that merely references it
    },
}

CLEAN = {
    "models": [{"name": "vae-group", "files": [{"file": "a.safetensors"}]}],
    "profiles": {"vae": ["vae-group"]},
}


def test_expand_refuses_a_name_that_is_both():
    with pytest.raises(profiles.ProfileError, match="both a model group and a profile"):
        profiles.expand(COLLIDING, "shared-vae")


def test_expand_refuses_even_when_reached_indirectly():
    """`downstream` does not collide; the name it REACHES does. Checking only
    the requested name would let the collision through one level down."""
    with pytest.raises(profiles.ProfileError, match="both a model group and a profile"):
        profiles.expand(COLLIDING, "downstream")


def test_validate_all_reports_the_collision_once_not_once_per_profile():
    """A collision is a property of the MANIFEST. Letting expand() raise for
    every profile turns one defect into N identical problems."""
    problems = profiles.validate_all(COLLIDING)
    hits = [p for p in problems if "both a model group and a profile" in p]
    assert len(hits) == 1, problems


def test_a_clean_manifest_still_expands():
    assert profiles.expand(CLEAN, "vae") == ["vae-group"]
    assert profiles.validate_all(CLEAN) == []


# ---- build refuses too, and this one is load-bearing -----------------------
#
# `resolve` WITHOUT --profile never calls expand() at all, so an expand()-only
# refusal still lets a full resolve accept a colliding manifest. Refusing at
# assembly time means the manifest is never written in the first place.

def src(root: pathlib.Path, name: str, body: dict) -> None:
    p = root / f"{name}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(body, sort_keys=False))


@pytest.fixture
def colliding_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "models"
    root.mkdir()
    src(root, "_meta", {"name": "s"})
    src(root, "shared/vae", {"groups": [{"name": "shared-vae", "files": [{"file": "a"}]}]})
    src(root, "profiles", {"shared-vae": ["shared-vae"]})
    return root


def test_build_refuses_to_write_a_colliding_manifest(colliding_tree):
    with pytest.raises(build.BuildError, match="both a model group and a profile"):
        build.render(colliding_tree)


def test_build_cli_exits_1_and_writes_nothing(colliding_tree, tmp_path):
    out = tmp_path / "comfy.yaml"
    r = runner.invoke(app, ["build", str(colliding_tree), "-O", str(out)])
    assert r.exit_code == 1
    assert not out.exists(), "a colliding manifest reached disk"


def test_resolve_cli_exits_2_on_a_colliding_profile(tmp_path):
    """Exit 2 = the request was wrong. test_cli_contract pins that meaning, and
    a manifest naming one thing twice is a wrong request, not a failed one."""
    m = tmp_path / "comfy.yaml"
    m.write_text(yaml.safe_dump(COLLIDING))
    r = runner.invoke(app, ["resolve", str(m), "--profile", "shared-vae"])
    assert r.exit_code == 2, r.output
