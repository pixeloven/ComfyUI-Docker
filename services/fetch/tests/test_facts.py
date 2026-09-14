"""`comfyfetch facts` — what a model IS, versus what its filename claims.

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

from comfyfetch import facts

FIX = pathlib.Path(__file__).parent / "fixtures" / "facts"


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
    shas = json.loads((FIX / "shas.json").read_text())
    shas.pop("4xUltrasharp_4xUltrasharpV10.pt", None)

    rendered = facts.render(
        lineage, headers=headers, shas=shas, token=None, generated="2026-09-12",
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
    full = json.loads((FIX / "shas.json").read_text())
    assert "4xUltrasharp_4xUltrasharpV10.pt" in full

    rendered = facts.render(
        lineage, headers=headers, shas=full, token=None, generated="2026-09-12"
    )
    assert "4xUltrasharp_4xUltrasharpV10.pt" in rendered


def test_the_attribution_line_is_a_parameter_not_a_content_change(civitai, headers):
    """Renaming the generator must not read as the facts having changed."""
    lineage = yaml.safe_load((FIX / "upscalers.yaml").read_text())
    shas = json.loads((FIX / "shas.json").read_text())
    a = facts.render(lineage, headers=headers, shas=shas, token=None,
                     generated="2026-09-12", generator="one")
    b = facts.render(lineage, headers=headers, shas=shas, token=None,
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

    from comfyfetch.cli import app

    sources = tmp_path / "models"
    sources.mkdir()
    (sources / "_meta.yaml").write_text("name: s\n")
    (FIX / "upscalers.yaml").read_bytes()
    (sources / "up.yaml").write_bytes((FIX / "upscalers.yaml").read_bytes())

    lock = tmp_path / "lock.yaml"
    shas = json.loads((FIX / "shas.json").read_text())
    lock.write_text(yaml.safe_dump({
        "models": [{"model": n, "hashes": [{"type": "SHA256", "hash": h}]}
                   for n, h in shas.items()]}))

    headers_file = tmp_path / "headers.json"
    headers_file.write_bytes((FIX / "headers.json").read_bytes())

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

    from comfyfetch.cli import app

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
