"""`comfyctl fetch facts` — what a model IS, versus what its filename claims.

Every network response is REPLAYED from a recording, so this suite is offline
and deterministic. That matters more here than elsewhere: the sidecars carry
live Civitai fields (`nsfw`, `trainedWords`, version names) that uploaders edit,
so a test hitting the network would go red for reasons unrelated to the code.
"""

import json
import pathlib

import pytest
import respx
import yaml
from httpx import Response

from comfyctl.fetch import facts

FIX = pathlib.Path(__file__).parent / "fixtures" / "facts"

# The recorded headers and shas are keyed by basename. Sidecars, and the maps
# render() joins on, are keyed by INSTALL PATH since #153; every file in the
# upscalers lineage installs here.
UPSCALERS = "models/upscale_models/"


def by_path(by_name: dict) -> dict:
    return {UPSCALERS + name: value for name, value in by_name.items()}


@pytest.fixture
def civitai():
    """Replay the recorded corpus; anything unrecorded is a 404, not a hang."""
    by_hash = json.loads((FIX / "by-hash.json").read_text())
    by_id = json.loads((FIX / "by-id.json").read_text())
    with respx.mock(assert_all_called=False) as mock:
        def hash_route(request):
            sha = request.url.path.rsplit("/", 1)[-1]
            body = by_hash.get(sha)
            if body is None or "_status" in (body or {}):
                return Response(404, json={})
            return Response(200, json=body)

        def id_route(request):
            vid = request.url.path.rsplit("/", 1)[-1]
            body = by_id.get(vid)
            if body is None or "_status" in (body or {}):
                return Response(404, json={})
            return Response(200, json=body)

        mock.get(url__regex=r".*/model-versions/by-hash/.*").mock(side_effect=hash_route)
        mock.get(url__regex=r".*/model-versions/\d+$").mock(side_effect=id_route)
        yield mock


@pytest.fixture
def headers():
    return json.loads((FIX / "headers.json").read_text())


# ---- the two traps, which are the reason this verb exists ------------------

def test_ss_base_model_version_is_never_used_for_lineage(civitai, headers):
    """It reports `sdxl_base_v1-0` for essentially every SDXL file. That is the
    ARCHITECTURE, not the finetune, and treating it as lineage mislabels the
    entire store."""
    assert any(h.get("ss_base_model_version") for h in headers.values()), "fixture lost its point"
    record = facts.describe(
        "illustrij_v18.safetensors",
        header=headers.get("illustrij_v18.safetensors", {}),
        sha=None,
        token=None,
    )
    assert "sdxl_base_v1-0" not in json.dumps(record)


def test_lineage_is_never_inferred_from_the_install_path(civitai, headers):
    """The path records where a file was FILED. It was wrong for 2 of 48 loras
    and 1 of 16 checkpoints in a real store, which is why `describe` is not
    given one."""
    import inspect
    params = set(inspect.signature(facts.describe).parameters)
    assert "install" not in params and "path" not in params


# ---- the authority chain ---------------------------------------------------

def test_trained_on_comes_from_the_header_not_the_filename(civitai, headers):
    name, header = next(
        (n, h) for n, h in headers.items()
        if (h.get("ss_sd_model_name") or "").endswith(".safetensors")
        and not h["ss_sd_model_name"][0].isdigit()
    )
    record = facts.describe(name, header=header, sha=None, token=None)
    assert record["trained_on"] == header["ss_sd_model_name"]


def test_a_numeric_ss_sd_model_name_is_resolved_through_civitai(civitai, headers):
    """Trainers record a bare Civitai version id. Left unresolved it is a number
    nobody can act on."""
    name, header = next(
        (n, h) for n, h in headers.items()
        if (h.get("ss_sd_model_name") or "")[:1].isdigit()
    )
    record = facts.describe(name, header=header, sha=None, token=None)
    assert record["trained_on"] and not record["trained_on"][0].isdigit()


def test_an_unresolvable_id_is_recorded_as_unresolved_not_dropped(civitai):
    record = facts.describe(
        "x.safetensors", header={"ss_sd_model_name": "999999999.safetensors"},
        sha=None, token=None,
    )
    assert "unresolved" in record["trained_on"]


def test_declared_base_comes_from_the_content_hash(civitai):
    by_hash = json.loads((FIX / "by-hash.json").read_text())
    sha, body = next((s, b) for s, b in by_hash.items() if b.get("baseModel"))
    record = facts.describe("whatever-the-file-is-called.safetensors",
                            header={}, sha=sha, token=None)
    assert record["declared_base"] == body["baseModel"]


def test_a_civitai_failure_means_unidentified_not_fatal(civitai):
    """An audit tool that dies on one bad lookup audits nothing."""
    record = facts.describe("x.safetensors", header={}, sha="f" * 64, token=None)
    assert record == {} or "declared_base" not in record


# ---- the byte-diff: the test that actually proves the port ------------------

def test_render_is_byte_identical_given_the_inputs_the_original_run_had(civitai, headers):
    """THE bar. `comfyfetch build` met it and caught a defect doing so; anything
    less is reassurance rather than proof.

    `shas` is trimmed to what the ORIGINAL run was given -- see the next test
    for why that trim is the interesting part.
    """
    committed = (FIX / "upscalers.facts.yaml").read_text()
    lineage = yaml.safe_load((FIX / "upscalers.yaml").read_text())
    shas = by_path(json.loads((FIX / "shas.json").read_text()))
    shas.pop(UPSCALERS + "4xUltrasharp_4xUltrasharpV10.pt", None)

    rendered = facts.render(
        lineage, headers=by_path(headers), shas=shas, token=None, generated="2026-09-12",
        generator="scripts/comfyui-model-facts.py",
    )
    assert rendered == committed


def test_taking_shas_from_the_lock_finds_a_file_the_original_run_missed(civitai, headers):
    """The original took a HAND-BUILT name->sha map as argv[1]. Whatever was
    left out of that map was silently never looked up -- and one file was.

    Deriving the shas from the lock instead is the whole reason the interface
    changed, and this is the evidence that it was not cosmetic.
    """
    lineage = yaml.safe_load((FIX / "upscalers.yaml").read_text())
    full = by_path(json.loads((FIX / "shas.json").read_text()))
    assert UPSCALERS + "4xUltrasharp_4xUltrasharpV10.pt" in full

    rendered = facts.render(
        lineage, headers=by_path(headers), shas=full, token=None, generated="2026-09-12"
    )
    assert UPSCALERS + "4xUltrasharp_4xUltrasharpV10.pt" in rendered


def test_the_attribution_line_is_a_parameter_not_a_content_change(civitai, headers):
    """Renaming the generator must not read as the facts having changed."""
    lineage = yaml.safe_load((FIX / "upscalers.yaml").read_text())
    shas = by_path(json.loads((FIX / "shas.json").read_text()))
    a = facts.render(lineage, headers=by_path(headers), shas=shas, token=None,
                     generated="2026-09-12", generator="one")
    b = facts.render(lineage, headers=by_path(headers), shas=shas, token=None,
                     generated="2026-09-12", generator="two")
    assert a != b
    assert a.split("\n", 1)[1] == b.split("\n", 1)[1]


# ---- the store and the repo are not always on the same machine -------------

def test_headers_can_be_supplied_instead_of_read_from_a_store(civitai, tmp_path):
    """`facts` needs safetensors headers AND the lineage sources, and those are
    not always reachable from one place: a Kubernetes store is inside the
    cluster while the sources are in a git checkout outside it.

    Reading headers is a separate step from resolving them, so the CLI accepts
    them pre-extracted. Without this the verb is unusable in exactly the
    deployment it was written for.
    """
    from typer.testing import CliRunner

    from comfyctl.fetch.cli import app

    sources = tmp_path / "models"
    sources.mkdir()
    (sources / "_meta.yaml").write_text("name: s\n")
    (FIX / "upscalers.yaml").read_bytes()
    (sources / "up.yaml").write_bytes((FIX / "upscalers.yaml").read_bytes())

    lock = tmp_path / "lock.yaml"
    shas = json.loads((FIX / "shas.json").read_text())
    lock.write_text(yaml.safe_dump({
        "models": [{"model": n, "paths": [{"path": UPSCALERS + n}],
                    "hashes": [{"type": "SHA256", "hash": h}]}
                   for n, h in shas.items()]}))

    headers_file = tmp_path / "headers.json"
    headers_file.write_text(json.dumps(by_path(json.loads((FIX / "headers.json").read_text()))))

    result = CliRunner().invoke(app, [
        "facts", str(sources), str(lock),
        "--headers", str(headers_file), "--generated", "2026-09-12",
    ])
    assert result.exit_code == 0, result.output
    written = (sources / "up.facts.yaml").read_text()
    assert "declared_base: Upscaler" in written


def test_headers_and_store_are_mutually_exclusive(tmp_path):
    """Two sources for one input is a wrong request, not a merge."""
    from typer.testing import CliRunner

    from comfyctl.fetch.cli import app

    (tmp_path / "m").mkdir()
    lock = tmp_path / "l.yaml"
    lock.write_text("models: []\n")
    h = tmp_path / "h.json"
    h.write_text("{}")
    result = CliRunner().invoke(app, [
        "facts", str(tmp_path / "m"), str(lock),
        "--headers", str(h), "--store", str(tmp_path),
    ])
    assert result.exit_code == 2


# ---- same basename, different files (#153) ---------------------------------
#
# Basenames repeat: `diffusion_pytorch_model.safetensors` is HuggingFace's
# default, and a real store carries two `qwen_3_4b.safetensors` from different
# repos. Joined by name, one file got the other's header and hash.

SAME_NAME = {"groups": [
    {"name": "enc-a", "files": [{"source": "hf:org-a/repo", "file": "qwen_3_4b.safetensors",
                                 "install": "models/text_encoders/"}]},
    {"name": "enc-b", "files": [{"source": "hf:org-b/repo", "file": "qwen_3_4b.safetensors",
                                 "install": "models/clip/"}]},
]}
A, B = "models/text_encoders/qwen_3_4b.safetensors", "models/clip/qwen_3_4b.safetensors"


def _safetensors(path: pathlib.Path, meta: dict) -> None:
    import struct
    path.parent.mkdir(parents=True, exist_ok=True)
    head = json.dumps({"__metadata__": meta}).encode()
    path.write_bytes(struct.pack("<Q", len(head)) + head)


def test_same_named_files_each_keep_their_own_header(tmp_path):
    """The issue's repro, offline: no hashes, and names that need no lookup."""
    from typer.testing import CliRunner

    from comfyctl.fetch.cli import app

    store, src = tmp_path / "store", tmp_path / "src"
    _safetensors(store / A, {"ss_sd_model_name": "base-A.safetensors"})
    _safetensors(store / B, {"ss_sd_model_name": "base-B.safetensors"})
    src.mkdir()
    (src / "lineage.yaml").write_text(yaml.safe_dump(SAME_NAME))
    lock = tmp_path / "lock.yaml"
    lock.write_text(yaml.safe_dump({"models": [
        {"model": "qwen_3_4b.safetensors", "paths": [{"path": A}]},
        {"model": "qwen_3_4b.safetensors", "paths": [{"path": B}]}]}))

    result = CliRunner().invoke(app, ["facts", str(src), str(lock), "--store", str(store),
                                      "--generated", "2026-09-29"])
    assert result.exit_code == 0, result.output
    files = yaml.safe_load((src / "lineage.facts.yaml").read_text())["files"]
    assert files == {A: {"trained_on": "base-A.safetensors"},
                     B: {"trained_on": "base-B.safetensors"}}


def test_same_named_files_each_keep_their_own_hash(civitai):
    """The hash half: each file's by-hash lookup is its own."""
    by_hash = json.loads((FIX / "by-hash.json").read_text())
    pony, sdxl = (next(s for s, b in by_hash.items() if (b or {}).get("baseModel") == base)
                  for base in ("Pony", "SDXL 1.0"))
    rendered = facts.render(SAME_NAME, headers={}, shas={A: pony, B: sdxl},
                            token=None, generated="2026-09-29")
    files = yaml.safe_load(rendered)["files"]
    assert (files[A]["declared_base"], files[B]["declared_base"]) == ("Pony", "SDXL 1.0")


def test_headers_keyed_by_basename_are_refused(tmp_path):
    """A pre-6.0.0 headers file is keyed by basename. Silently matching nothing
    would write sidecars with no headers at all, so it is a wrong request."""
    from typer.testing import CliRunner

    from comfyctl.fetch.cli import app

    (tmp_path / "src").mkdir()
    lock = tmp_path / "lock.yaml"
    lock.write_text("models: []\n")
    h = tmp_path / "h.json"
    h.write_text(json.dumps({"qwen_3_4b.safetensors": {}}))
    result = CliRunner().invoke(app, ["facts", str(tmp_path / "src"), str(lock),
                                      "--headers", str(h)])
    assert result.exit_code == 2, result.output
    assert "install paths" in result.output


# ---- facts --check: the offline freshness gate (#155) ----------------------

def _sidecar(path: pathlib.Path, files: dict) -> None:
    path.write_text(yaml.safe_dump({"generated": "2026-09-29", "files": files}))


def _check(src: pathlib.Path, *extra: str):
    from typer.testing import CliRunner

    from comfyctl.fetch.cli import app

    return CliRunner().invoke(app, ["facts", str(src), "--check", "-o", "json", *extra])


def test_check_passes_when_every_key_is_declared(tmp_path):
    """A declared file with no entry is fine: render() omits a file with
    nothing measurable. Only the other direction is stale."""
    (tmp_path / "lineage.yaml").write_text(yaml.safe_dump(SAME_NAME))
    _sidecar(tmp_path / "lineage.facts.yaml", {A: {"trained_on": "x"}})
    result = _check(tmp_path)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"sidecars": 1, "problems": [], "ok": True}


def test_check_fails_a_key_the_lineage_no_longer_declares(tmp_path):
    (tmp_path / "lineage.yaml").write_text(yaml.safe_dump(SAME_NAME))
    _sidecar(tmp_path / "lineage.facts.yaml",
             {A: {"trained_on": "x"}, "models/loras/gone.safetensors": {"nsfw": True}})
    result = _check(tmp_path)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert len(payload["problems"]) == 1
    assert "models/loras/gone.safetensors" in payload["problems"][0]


def test_check_fails_a_sidecar_with_no_lineage(tmp_path):
    _sidecar(tmp_path / "orphan.facts.yaml", {A: {"trained_on": "x"}})
    result = _check(tmp_path)
    assert result.exit_code == 1
    assert "no sibling lineage orphan.yaml" in json.loads(result.stdout)["problems"][0]


def test_check_names_a_pre_6_sidecar_and_how_to_fix_it(tmp_path):
    """Sidecars written before 6.0.0 are keyed by basename. Each such key is
    stale, and the message says to regenerate."""
    (tmp_path / "lineage.yaml").write_text(yaml.safe_dump(SAME_NAME))
    _sidecar(tmp_path / "lineage.facts.yaml", {"qwen_3_4b.safetensors": {"trained_on": "x"}})
    result = _check(tmp_path)
    assert result.exit_code == 1
    assert "regenerate" in json.loads(result.stdout)["problems"][0]


def test_check_takes_no_lock_store_or_network(tmp_path):
    lock = tmp_path / "lock.yaml"
    lock.write_text("models: []\n")
    assert _check(tmp_path, str(lock)).exit_code == 2


def test_check_passes_on_what_facts_just_wrote(tmp_path):
    """The round trip: a fresh sidecar is never stale."""
    from typer.testing import CliRunner

    from comfyctl.fetch.cli import app

    store, src = tmp_path / "store", tmp_path / "src"
    _safetensors(store / A, {"ss_sd_model_name": "base-A.safetensors"})
    src.mkdir()
    (src / "lineage.yaml").write_text(yaml.safe_dump(SAME_NAME))
    lock = tmp_path / "lock.yaml"
    lock.write_text("models: []\n")
    wrote = CliRunner().invoke(app, ["facts", str(src), str(lock), "--store", str(store)])
    assert wrote.exit_code == 0, wrote.output
    assert (src / "lineage.facts.yaml").is_file()
    assert _check(src).exit_code == 0
