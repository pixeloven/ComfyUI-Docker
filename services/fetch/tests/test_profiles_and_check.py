"""Profile expansion and manifest/lock consistency. All offline."""
import pytest
import yaml
from comfyfetch import check as C
from comfyfetch import lockfile, profiles

MANIFEST = {
    "models": [{"name": "a"}, {"name": "b"}],
    "profiles": {
        "one": ["a"],
        "both": ["one", "b"],
        "self": ["self"],
        "m1": ["m2"], "m2": ["m1"],
        "three_a": ["three_b"], "three_b": ["three_c"], "three_c": ["three_a"],
        "typo": ["nope"],
    },
}


def test_profiles_compose_by_set_union():
    assert set(profiles.expand(MANIFEST, "both")) == {"a", "b"}


@pytest.mark.parametrize("name", ["self", "m1", "three_a"])
def test_every_cycle_length_is_caught(name):
    """A self-reference check would miss `a -> b -> a`, which is the same defect."""
    with pytest.raises(profiles.ProfileError, match="cycle"):
        profiles.expand(MANIFEST, name)


def test_unknown_member_is_caught():
    with pytest.raises(profiles.ProfileError, match="neither a model nor a profile"):
        profiles.expand(MANIFEST, "typo")


def test_unknown_profile_name():
    with pytest.raises(profiles.ProfileError, match="no such profile"):
        profiles.expand(MANIFEST, "absent")


def _load(fixtures, name):
    return lockfile.load(fixtures / name)


def test_agreeing_pair_passes(fixtures):
    problems, declared, locked = C.check(
        _load(fixtures, "manifest-for-lock-good.yaml"), _load(fixtures, "lock-good.yaml"))
    assert problems == []
    assert declared == locked == 1


def test_unhashed_lock_entry_is_rejected(fixtures):
    problems, *_ = C.check(
        _load(fixtures, "manifest-for-lock-good.yaml"), _load(fixtures, "lock-no-hash.yaml"))
    assert any("NO SHA256" in p for p in problems)


def test_profile_problems_surface_in_check(fixtures):
    problems, *_ = C.check(
        _load(fixtures, "manifest-profile-cycle.yaml"), _load(fixtures, "lock-good.yaml"))
    assert any("BAD PROFILE" in p for p in problems)


def test_undeclared_lock_entry_is_rejected(fixtures):
    manifest = {"models": [], "profiles": {}}
    problems, *_ = C.check(manifest, _load(fixtures, "lock-good.yaml"))
    assert any("NOT DECLARED" in p for p in problems)


def test_empty_sides_cannot_compare_equal(fixtures):
    """Two empty sides diff clean; the gate must call that broken, not passing."""
    problems, *_ = C.check({"models": [], "profiles": {}}, {"models": []})
    assert any("GATE BROKEN" in p for p in problems)


def test_install_path_is_derivable_offline():
    assert lockfile.install_path(
        {"install": "models/loras/", "file": "a/b/c.safetensors"}) == "models/loras/c.safetensors"
    assert lockfile.install_path(
        {"install": "models/loras/", "as": "x.safetensors"}) == "models/loras/x.safetensors"


# --- check --profile ---------------------------------------------------------
#
# The profile filter had no test at all: deleting the two lines that apply it
# left the whole suite green, which meant `check --profile X` could have been
# checking the ENTIRE manifest against one profile's lock and reporting the
# other profiles' files as NOT LOCKED. That is the shape of failure that makes
# a gate useless -- it fails for a reason that is not a mistake, so people stop
# reading it.

def _two_group_manifest() -> dict:
    return {
        "models": [
            {"name": "a", "files": [{"source": "hf:x/y", "file": "a.safetensors",
                                     "install": "models/loras/"}]},
            {"name": "b", "files": [{"source": "hf:x/y", "file": "b.safetensors",
                                     "install": "models/loras/"}]},
        ],
        "profiles": {"just-a": ["a"], "both": ["a", "b"]},
    }


def _lock_for(*names: str) -> dict:
    return {"models": [{"model": f"{n}.safetensors",
                        "paths": [{"path": f"models/loras/{n}.safetensors"}],
                        "hashes": [{"hash": "0" * 64, "type": "SHA256"}]}
                       for n in names]}


def test_a_profile_lock_is_checked_against_only_that_profile():
    problems, declared, locked = C.check(_two_group_manifest(), _lock_for("a"), "just-a")
    assert problems == []
    assert (declared, locked) == (1, 1)


def test_the_same_pair_fails_WITHOUT_the_profile():
    """The control. Without it the test above passes on a `check` that ignores
    --profile entirely, because a manifest-wide check of a full lock also
    passes -- the filter only shows up when the lock is a strict subset."""
    problems, declared, _ = C.check(_two_group_manifest(), _lock_for("a"))
    assert declared == 2
    assert any("NOT LOCKED" in p and "b.safetensors" in p for p in problems)


def test_a_profile_lock_carrying_a_foreign_entry_is_rejected():
    """Scoping must not become a way to ignore extras: an entry no profile
    declared is still NOT DECLARED."""
    problems, *_ = C.check(_two_group_manifest(), _lock_for("a", "b"), "just-a")
    assert any("NOT DECLARED" in p and "b.safetensors" in p for p in problems)


def test_an_unknown_profile_raises_rather_than_checking_everything():
    """Silently falling back to the whole manifest would make a typo in a CI
    invocation look like a passing narrower check."""
    with pytest.raises(profiles.ProfileError, match="no such profile"):
        C.check(_two_group_manifest(), _lock_for("a"), "nope")
