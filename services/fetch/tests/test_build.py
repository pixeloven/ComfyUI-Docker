"""Manifest assembly from per-lineage sources. All offline."""

import pathlib

import pytest
import yaml
from comfyfetch import build
from typer.testing import CliRunner

from comfyfetch.cli import app

runner = CliRunner()


def src(root: pathlib.Path, name: str, body: dict) -> pathlib.Path:
    p = root / f"{name}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(body, sort_keys=False))
    return p


@pytest.fixture
def tree(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "models"
    root.mkdir()
    src(root, "_meta", {"name": "s", "description": "d", "auth": {"h": "${T}"}})
    src(root, "shared/flux", {
        "family": "flux", "lineage": "flux2",
        "summary": "Two generations.\nNOT interchangeable.",
        "groups": [{"name": "flux2-diffusion", "files": [{"file": "a.safetensors"}]},
                   {"name": "flux2-vae", "files": [{"file": "b.safetensors"}]}]})
    src(root, "custom/sdxl", {
        "family": "sdxl", "lineage": "illustrious",
        "groups": [{"name": "sdxl-checkpoints", "files": [{"file": "c.safetensors"}]}]})
    src(root, "profiles", {"flux2": ["flux2-diffusion", "flux2-vae"]})
    src(root, "capabilities", {"gen": {"profiles": ["flux2"], "requires": ["vae"]}})
    return root


def test_groups_are_collected_across_the_whole_tree(tree):
    groups, _ = build.load_sources(tree)
    assert [g["name"] for g in groups] == [
        "sdxl-checkpoints", "flux2-diffusion", "flux2-vae"]


def test_reserved_filenames_are_not_treated_as_lineages(tree):
    """profiles.yaml and capabilities.yaml are copied through, not walked for
    groups -- walking them would find none and silently succeed, so the guard
    has to be explicit."""
    _, summaries = build.load_sources(tree)
    assert "profiles" not in summaries


def test_duplicate_group_names_are_fatal(tree):
    src(tree, "shared/other", {"groups": [{"name": "flux2-vae", "files": []}]})
    with pytest.raises(build.BuildError, match="duplicate group 'flux2-vae'"):
        build.load_sources(tree)


def test_a_group_without_a_name_is_fatal(tree):
    src(tree, "shared/bad", {"groups": [{"files": []}]})
    with pytest.raises(build.BuildError, match="without a name"):
        build.load_sources(tree)


def test_summary_is_reattached_above_its_lineage(tree):
    """A summary that lives only in the source file is invisible where the
    manifest is actually consumed. This is the whole reason build is not cat."""
    text, _ = build.render(tree)
    assert "  # Two generations.\n  # NOT interchangeable.\n  - name: flux2-diffusion" in text


def test_summary_is_emitted_once_per_lineage_not_once_per_group(tree):
    text, _ = build.render(tree)
    assert text.count("# Two generations.") == 1


def test_render_is_valid_yaml_and_keeps_profiles_and_capabilities(tree):
    text, counts = build.render(tree)
    doc = yaml.safe_load(text)
    assert counts == {"groups": 3, "profiles": 1, "capabilities": 1}
    assert doc["name"] == "s" and doc["auth"] == {"h": "${T}"}
    assert doc["profiles"]["flux2"] == ["flux2-diffusion", "flux2-vae"]


def test_sequences_are_indented_for_yamllint(tree):
    """safe_dump emits indentless sequences, which yamllint flags on every list
    item. The override is invisible to a parser, so only a text assertion
    catches a regression."""
    text, _ = build.render(tree)
    assert "\n  - name: flux2-diffusion" in text
    assert "    files:\n      - file:" in text


def test_render_is_deterministic(tree):
    assert build.render(tree)[0] == build.render(tree)[0]


def test_missing_meta_is_fatal(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(build.BuildError, match="no _meta.yaml"):
        build.render(tmp_path / "empty")


def test_a_tree_with_no_groups_is_fatal(tmp_path):
    root = tmp_path / "m"; root.mkdir()
    src(root, "_meta", {"name": "s"})
    with pytest.raises(build.BuildError, match="no groups"):
        build.render(root)


def test_header_is_prepended_verbatim(tree, tmp_path):
    h = tmp_path / "h.txt"; h.write_text("---\n# GENERATED\n")
    text, _ = build.render(tree, header=h.read_text())
    assert text.startswith("---\n# GENERATED\n")


# ---- CLI contract -----------------------------------------------------------

def test_check_reports_stale_and_exits_1(tree, tmp_path):
    out = tmp_path / "comfy.yaml"
    assert runner.invoke(app, ["build", str(tree), "-O", str(out)]).exit_code == 0
    out.write_text(out.read_text() + "# drifted\n")
    r = runner.invoke(app, ["build", str(tree), "-O", str(out), "--check"])
    assert r.exit_code == 1
    assert "STALE" in r.output


def test_check_passes_on_a_freshly_built_manifest(tree, tmp_path):
    out = tmp_path / "comfy.yaml"
    runner.invoke(app, ["build", str(tree), "-O", str(out)])
    r = runner.invoke(app, ["build", str(tree), "-O", str(out), "--check"])
    assert r.exit_code == 0, r.output


def test_check_without_out_is_a_usage_error_not_a_failure(tree):
    """Exit 2 means the request was wrong; exit 1 means the world was. A
    --check with nothing to compare against is the former."""
    r = runner.invoke(app, ["build", str(tree), "--check"])
    assert r.exit_code == 2


def test_check_on_a_missing_manifest_fails_rather_than_writing_one(tree, tmp_path):
    out = tmp_path / "absent.yaml"
    r = runner.invoke(app, ["build", str(tree), "-O", str(out), "--check"])
    assert r.exit_code == 1
    assert not out.exists()


def test_a_missing_source_directory_is_a_usage_error(tmp_path):
    r = runner.invoke(app, ["build", str(tmp_path / "nope")])
    assert r.exit_code == 2


def test_stdout_carries_the_artifact(tree):
    """Human output goes to stderr so redirecting stdout into a file stays
    correct -- the same contract resolve has."""
    r = runner.invoke(app, ["build", str(tree), "-o", "plain"])
    assert r.exit_code == 0
    assert yaml.safe_load(r.stdout)["name"] == "s"
