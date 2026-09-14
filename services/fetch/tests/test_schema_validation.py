"""`check` owns the definition of a valid manifest.

Until now a consumer wanting schema validation had to run `check-jsonschema`
against a path INSIDE a checkout of this repo -- which is the only reason some
of them keep a checkout at all. The tool owns the format, so it should own
saying whether a file conforms to it.
"""

import json
import pathlib

import pytest
import yaml
from typer.testing import CliRunner

from comfyfetch import schema
from comfyfetch.cli import app

runner = CliRunner()

MINIMAL = {
    "models": [
        {"name": "g", "files": [{"source": "hf:a/b", "install": "models/loras/"}]}
    ]
}


def write(path: pathlib.Path, doc: dict) -> pathlib.Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def test_the_schemas_ship_with_the_package(tmp_path):
    """Bundled as package data, not read from a checkout. A consumer running
    `uvx comfyfetch` has no checkout to point at."""
    assert schema.load("comfy") ["type"] == "object"
    assert schema.load("comfy-lock")["type"] == "object"


def test_a_typo_in_a_file_key_is_caught(tmp_path):
    """`additionalProperties: false` is the whole reason this validates at all:
    `instal:` silently installs nothing and reports success."""
    doc = {"models": [{"name": "g", "files": [
        {"source": "hf:a/b", "install": "models/loras/", "instal": "typo"}]}]}
    problems = schema.validate(doc, "comfy")
    assert problems and "instal" in problems[0]


def test_an_x_prefixed_key_is_allowed_anywhere_a_consumer_needs_one(tmp_path):
    """Typo protection and extensibility are not in tension if extensions are
    NAMED. `x-` is the convention OpenAPI settled on, and it keeps an unknown
    bare key an error.

    A real consumer carries 43 such keys -- trigger words a LoRA needs to fire,
    which generation of a family a file belongs to, and whether a checkpoint is
    all-in-one or split. None of that is comfyfetch's business, and all of it
    would be lost if the only options were "schema rejects it" or "schema stops
    checking".
    """
    doc = {"models": [{"name": "g", "files": [
        {"source": "hf:a/b", "install": "models/loras/",
         "x-triggers": ["score_9"], "x-generation": "2511"}]}]}
    assert schema.validate(doc, "comfy") == []


def test_capabilities_are_part_of_the_format_not_an_unchecked_passenger(tmp_path):
    """`capabilities:` was absent from the schema entirely, so it passed by
    accident -- the top level was simply not closed. Anything built on it was
    built on sand."""
    doc = dict(MINIMAL, capabilities={"gen": {"profiles": ["p"], "requires": ["vae"]}})
    assert schema.validate(doc, "comfy") == []
    assert "capabilities" in schema.load("comfy")["properties"]


def test_a_capability_naming_an_undeclared_profile_is_caught(tmp_path):
    doc = dict(MINIMAL,
               profiles={"p": ["g"]},
               capabilities={"gen": {"profiles": ["nope"], "requires": ["vae"]}})
    problems = schema.validate_semantics(doc)
    assert any("nope" in p for p in problems), problems


def test_a_capability_requiring_a_type_no_file_declares_is_caught(tmp_path):
    """A capability that requires `vae` and resolves zero is a graph that loads
    and cannot render. Structural, so it can be checked offline."""
    doc = dict(MINIMAL,
               profiles={"p": ["g"]},
               capabilities={"gen": {"profiles": ["p"], "requires": ["vae"]}})
    problems = schema.validate_semantics(doc)
    assert any("vae" in p for p in problems), problems


def test_a_capability_with_an_empty_requires_is_caught(tmp_path):
    doc = dict(MINIMAL, profiles={"p": ["g"]},
               capabilities={"gen": {"profiles": ["p"], "requires": []}})
    assert schema.validate_semantics(doc)


# ---- CLI -------------------------------------------------------------------

def test_check_reports_a_schema_violation_and_exits_1(tmp_path):
    m = write(tmp_path / "comfy.yaml", {"models": [{"name": "g", "files": [
        {"source": "hf:a/b", "install": "models/loras/", "instal": "typo"}]}]})
    lock = write(tmp_path / "lock.yaml", {"models": []})
    result = runner.invoke(app, ["check", str(m), str(lock)])
    assert result.exit_code == 1
    assert "instal" in result.output


def test_check_still_passes_on_the_repos_own_manifest():
    """The manifest this repo ships must satisfy the schema it publishes."""
    root = pathlib.Path(__file__).resolve().parents[3]
    doc = yaml.safe_load((root / "comfy.yaml").read_text())
    assert schema.validate(doc, "comfy") == []


# ---- --parent: a derived lock must be a verbatim subset --------------------

PARENT = {"models": [
    {"model": "a.safetensors", "url": "https://h/a", "paths": [{"path": "models/loras/a.safetensors"}],
     "hashes": [{"type": "SHA256", "hash": "a" * 64}]},
    {"model": "b.safetensors", "url": "https://h/b", "paths": [{"path": "models/vae/b.safetensors"}],
     "hashes": [{"type": "SHA256", "hash": "b" * 64}]},
]}


def test_a_derived_lock_that_is_a_subset_passes(tmp_path):
    child = {"models": [PARENT["models"][0]]}
    assert schema.subset_problems(child, PARENT) == []


def test_a_derived_lock_with_a_DIFFERENT_HASH_is_caught(tmp_path):
    """The invariant --from-lock exists to guarantee. Resolving each profile
    independently lets locks made minutes apart pin different upstream commits,
    and nothing downstream would ever notice."""
    drifted = json.loads(json.dumps(PARENT["models"][0]))
    drifted["hashes"][0]["hash"] = "c" * 64
    problems = schema.subset_problems({"models": [drifted]}, PARENT)
    assert problems and "a.safetensors" in problems[0]


def test_a_derived_lock_containing_an_entry_the_parent_lacks_is_caught(tmp_path):
    extra = {"model": "z.safetensors", "url": "https://h/z",
             "paths": [{"path": "models/loras/z.safetensors"}], "hashes": []}
    problems = schema.subset_problems({"models": [extra]}, PARENT)
    assert problems and "z.safetensors" in problems[0]


def test_check_parent_passes_on_a_clean_subset(tmp_path):
    """The control. Without it the drift test passes for ANY exit 1 -- and it
    did: the --parent wiring was missing entirely and both cases failed on an
    unrelated manifest/lock mismatch. A test that cannot distinguish the thing
    it is testing from the background is not a test."""
    parent = write(tmp_path / "everything.yaml", PARENT)
    child = write(tmp_path / "child.yaml", {"models": [PARENT["models"][0]]})
    m = write(tmp_path / "comfy.yaml", {"models": [{"name": "g", "files": [
        {"source": "hf:a/b", "install": "models/loras/", "as": "a.safetensors"}]}]})
    result = runner.invoke(app, ["check", str(m), str(child), "--parent", str(parent)])
    assert result.exit_code == 0, result.output
    assert "verbatim subset of" in result.output, result.output


def test_check_parent_exits_1_on_drift(tmp_path):
    parent = write(tmp_path / "everything.yaml", PARENT)
    drifted = json.loads(json.dumps(PARENT["models"][0]))
    drifted["hashes"][0]["hash"] = "c" * 64
    child = write(tmp_path / "child.yaml", {"models": [drifted]})
    m = write(tmp_path / "comfy.yaml", MINIMAL)
    result = runner.invoke(app, ["check", str(m), str(child), "--parent", str(parent)])
    assert result.exit_code == 1
    assert "differs from the parent lock" in result.output, result.output


# ---- assertions that FAIL if the feature is removed -------------------------
#
# Every test below was written after a mutation pass found eight features with
# no test that would notice their absence. A test that passes with the code
# deleted is documentation, not a test.

def test_the_top_level_is_closed():
    """The PR's headline claim was "capabilities passed because the top level
    was not closed". If that closure regresses, every unknown top-level key is
    silently accepted again."""
    assert schema.load("comfy")["additionalProperties"] is False
    assert schema.validate({"models": [], "nonsense": 1}, "comfy")


def test_an_x_key_is_allowed_at_GROUP_level_too():
    """Only the file level was covered. A consumer annotating a lineage rather
    than a file hits the group level first."""
    doc = {"models": [{"name": "g", "x-lineage": "flux2", "files": [
        {"source": "hf:a/b", "install": "models/loras/"}]}]}
    assert schema.validate(doc, "comfy") == []


def test_a_MALFORMED_capability_is_rejected():
    """`capabilities: {type: object}` would accept any garbage. The shape has to
    be checked, not merely the key's presence."""
    assert schema.validate(dict(MINIMAL, capabilities={"c": {"profiles": "notalist"}}), "comfy")
    assert schema.validate(dict(MINIMAL, capabilities={"c": {"profiles": []}}), "comfy")
    assert schema.validate(dict(MINIMAL, capabilities={"c": {"profiles": ["p"]}}), "comfy")
    assert schema.validate(dict(MINIMAL, capabilities={"c": {"profiles": ["p"],
                                                             "requires": ["vae"],
                                                             "typo": 1}}), "comfy")


def test_a_lock_entry_with_an_unknown_key_is_rejected():
    assert schema.validate({"models": [{"model": "a", "url": "https://h/a",
                                        "paths": [{"path": "models/loras/a"}],
                                        "nonsense": 1}]}, "comfy-lock")


def test_the_CLI_runs_the_semantic_checks_not_just_the_schema(tmp_path):
    """Wired, not merely written. The --parent wiring silently did not apply
    once already."""
    m = write(tmp_path / "comfy.yaml",
              dict(MINIMAL, profiles={"p": ["g"]},
                   capabilities={"gen": {"profiles": ["p"], "requires": ["vae"]}}))
    lock = write(tmp_path / "lock.yaml", {"models": []})
    result = runner.invoke(app, ["check", str(m), str(lock)])
    assert result.exit_code == 1
    assert "requires type 'vae'" in result.output, result.output


def test_the_CLI_validates_the_LOCK_schema_too(tmp_path):
    m = write(tmp_path / "comfy.yaml", MINIMAL)
    lock = write(tmp_path / "lock.yaml", {"models": [{"model": "a", "nonsense": 1}]})
    result = runner.invoke(app, ["check", str(m), str(lock)])
    assert result.exit_code == 1
    assert "lock:" in result.output, result.output


def test_a_schema_problem_STOPS_the_run_rather_than_being_mentioned(tmp_path):
    """Reported-but-not-fatal would let a typo through while looking checked.
    The consistency report must not appear at all."""
    m = write(tmp_path / "comfy.yaml", {"models": [{"name": "g", "files": [
        {"source": "hf:a/b", "install": "models/loras/", "instal": "typo"}]}]})
    lock = write(tmp_path / "lock.yaml", {"models": []})
    result = runner.invoke(app, ["check", str(m), str(lock)])
    assert result.exit_code == 1
    assert "declared:" not in result.output, result.output


def test_json_output_carries_the_reason_on_every_failure_path(tmp_path):
    """`Out.problem` is a no-op under --output json, so a bare `raise Exit(1)`
    gave a machine consumer exit 1 with ZERO bytes on either stream."""
    m = write(tmp_path / "comfy.yaml", {"models": [{"name": "g", "files": [
        {"source": "hf:a/b", "install": "models/loras/", "instal": "typo"}]}]})
    lock = write(tmp_path / "lock.yaml", {"models": []})
    result = runner.invoke(app, ["check", str(m), str(lock), "--output", "json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert any("instal" in p for p in payload["problems"]), payload


def test_a_structurally_broken_manifest_reports_the_schema_error_not_a_traceback(tmp_path):
    """validate_semantics calls .get() on whatever it is handed. Running it on
    a manifest that failed STRUCTURE shows a Python traceback instead of the
    message that explains the problem."""
    # `capabilities: oops` rather than `models: oops` -- the latter is
    # independently guarded by an isinstance check, so it passes with the gate
    # REMOVED and proves nothing.
    m = write(tmp_path / "comfy.yaml", dict(MINIMAL, capabilities="oops"))
    lock = write(tmp_path / "lock.yaml", {"models": []})
    result = runner.invoke(app, ["check", str(m), str(lock)])
    assert result.exit_code == 1
    assert "Traceback" not in result.output, result.output
    assert "is not of type" in result.output, result.output


def test_two_entries_sharing_a_basename_are_not_confused(tmp_path):
    """A real lock carries two `qwen_3_4b.safetensors` from different repos --
    one file shared by two lineages, declared by each so either resolves alone.
    Keying the parent by filename compares a child against the wrong entry and
    invents drift."""
    parent = {"models": [
        {"model": "dup.safetensors", "url": "https://h/one",
         "paths": [{"path": "models/text_encoders/a.safetensors"}], "hashes": []},
        {"model": "dup.safetensors", "url": "https://h/two",
         "paths": [{"path": "models/text_encoders/b.safetensors"}], "hashes": []},
    ]}
    child = {"models": [parent["models"][0]]}
    assert schema.subset_problems(child, parent) == []


def test_requires_is_checked_against_the_capabilitys_OWN_profiles(tmp_path):
    """Manifest-wide collection makes this nearly vacuous: a capability whose
    profiles resolve only upscalers would satisfy `requires: [diffusion_models]`
    because some unrelated lineage declares one."""
    doc = {
        "models": [
            {"name": "up", "files": [{"source": "hf:a/b", "install": "models/upscale_models/",
                                      "type": "upscale_models"}]},
            {"name": "dm", "files": [{"source": "hf:c/d", "install": "models/diffusion_models/",
                                      "type": "diffusion_models"}]},
        ],
        "profiles": {"common": ["up"], "gen": ["dm"]},
        "capabilities": {"upscale": {"profiles": ["common"], "requires": ["diffusion_models"]}},
    }
    problems = schema.validate_semantics(doc)
    assert any("diffusion_models" in p for p in problems), problems


def test_a_capability_whose_profiles_DO_resolve_its_types_passes(tmp_path):
    doc = {
        "models": [{"name": "dm", "files": [{"source": "hf:c/d",
                                             "install": "models/diffusion_models/",
                                             "type": "diffusion_models"}]}],
        "profiles": {"gen": ["dm"]},
        "capabilities": {"g": {"profiles": ["gen"], "requires": ["diffusion_models"]}},
    }
    assert schema.validate_semantics(doc) == []


def test_a_profile_fault_is_reported_AS_ITSELF_not_as_a_missing_type(tmp_path):
    """The regression this PR nearly shipped.

    Everything in validate_semantics walks profiles to find types, so a profile
    that cannot expand contributes none and makes every `requires` look unmet.
    Swallowing the expansion error reported "requires type 'diffusion_models',
    which none of its profiles resolve" -- sending the reader after a phantom
    type problem while a group/profile name collision went unmentioned.
    """
    doc = {
        "models": [{"name": "flux", "files": [{"source": "hf:a/b",
                                               "install": "models/diffusion_models/",
                                               "type": "diffusion_models"}]}],
        "profiles": {"flux": ["flux"]},          # collides with the group
        "capabilities": {"gen": {"profiles": ["flux"], "requires": ["diffusion_models"]}},
    }
    problems = schema.validate_semantics(doc)
    assert any("both a model group and a profile" in p for p in problems), problems
    assert not any("none of its profiles resolve" in p for p in problems), problems


def test_fetch_refuses_a_malformed_lock_before_touching_the_network(tmp_path):
    """fetch WRITES. A malformed lock puts files in the wrong place, or none at
    all, after the network has already been used."""
    lock = write(tmp_path / "lock.yaml", {"models": [{"model": "a", "nonsense": 1}]})
    result = runner.invoke(app, ["fetch", str(lock), str(tmp_path / "ws")])
    assert result.exit_code == 1
    assert "nonsense" in result.output, result.output


def test_a_malformed_PARENT_lock_is_reported_as_the_parents_problem(tmp_path):
    """Otherwise it fails deep inside the subset comparison on a missing key."""
    m = write(tmp_path / "comfy.yaml", MINIMAL)
    child = write(tmp_path / "child.yaml", {"models": [PARENT["models"][0]]})
    parent = write(tmp_path / "parent.yaml",
                   {"models": [dict(PARENT["models"][0], nonsense=1)]})
    result = runner.invoke(app, ["check", str(m), str(child), "--parent", str(parent)])
    assert result.exit_code == 1
    assert "parent:" in result.output, result.output
