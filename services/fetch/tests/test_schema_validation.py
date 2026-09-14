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
    assert "differ from" not in result.output, result.output


def test_check_parent_exits_1_on_drift(tmp_path):
    parent = write(tmp_path / "everything.yaml", PARENT)
    drifted = json.loads(json.dumps(PARENT["models"][0]))
    drifted["hashes"][0]["hash"] = "c" * 64
    child = write(tmp_path / "child.yaml", {"models": [drifted]})
    m = write(tmp_path / "comfy.yaml", MINIMAL)
    result = runner.invoke(app, ["check", str(m), str(child), "--parent", str(parent)])
    assert result.exit_code == 1
    assert "differs from the parent lock" in result.output, result.output
