#!/usr/bin/env python3
"""Stdlib-only helpers shared by the harness's setup and check scripts.

Every check reads ComfyUI's HTTP API or the scratch filesystem, never an agent
transcript. Usage: harness.py <command> [args]; see COMMANDS at the bottom.
"""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
DATA = Path(os.environ.get("HARNESS_DATA", "/tmp/comfyui-harness"))
# The agent's working directory. Its file tools are confined to it, so it
# cannot read answers.json or the ground-truth dump.
WORKSPACE = DATA / "workspace"

INPUT_IMAGE = "harness-input.png"


class CheckFailed(Exception):
    pass


# --- HTTP ---------------------------------------------------------------------


def http(method: str, path: str, body: object | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(COMFY_URL + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def get(path: str) -> object:
    status, body = http("GET", path)
    if status != 200:
        raise CheckFailed(f"GET {path} returned HTTP {status}")
    return body


def history() -> dict:
    return get("/history?max_items=10000")  # type: ignore[return-value]


# --- History markers: "a NEW entry" means one not present when setup ran -------


def marker_path(task: str) -> Path:
    return RESULTS / f"{task}.history-before.json"


def mark(task: str) -> None:
    marker_path(task).write_text(json.dumps(sorted(history())))


def new_entries(task: str) -> dict:
    p = marker_path(task)
    if not p.exists():
        raise CheckFailed(
            f"no history marker for {task}; run tasks/{task}/setup.sh first"
        )
    before = set(json.loads(p.read_text()))
    return {k: v for k, v in history().items() if k not in before}


def completed(entry: dict) -> bool:
    st = entry.get("status") or {}
    return bool(st.get("completed")) and st.get("status_str") == "success"


def graph(entry: dict) -> dict:
    # A history entry's "prompt" is [number, prompt_id, graph, extra, outputs].
    return entry["prompt"][2]


def class_types(entry: dict) -> set[str]:
    return {n.get("class_type") for n in graph(entry).values()}


# --- PNG (write the input; read an output's size and pixels) ------------------


def write_png(path: Path, width: int, height: int) -> None:
    """A horizontal black-to-white gradient, 8-bit RGB."""
    rows = b"".join(
        b"\x00" + bytes(v for x in range(width) for v in (x * 255 // (width - 1),) * 3)
        for _ in range(height)
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        c = kind + payload
        return struct.pack(">I", len(payload)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def read_png(path: Path) -> tuple[int, int, list[list[int]]]:
    """Width, height and per-row grey values of an 8-bit RGB/RGBA/grey PNG."""
    blob = path.read_bytes()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise CheckFailed(f"{path.name} is not a PNG")
    pos, idat, ihdr = 8, b"", None
    while pos < len(blob):
        (length,) = struct.unpack(">I", blob[pos : pos + 4])
        kind, payload = blob[pos + 4 : pos + 8], blob[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat += payload
        pos += 12 + length
    if ihdr is None:
        raise CheckFailed(f"{path.name} has no IHDR")
    w, h, depth, ctype, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or channels is None or interlace:
        # Size is still valid; pixels are not decodable here.
        return w, h, []
    raw, stride, prev, rows = (
        zlib.decompress(idat),
        w * channels,
        bytearray(w * channels),
        [],
    )
    for y in range(h):
        f, line = (
            raw[y * (stride + 1)],
            bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]),
        )
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b, c = prev[i], prev[i - channels] if i >= channels else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (
                    line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)
                ) & 255
        rows.append([line[x * channels] for x in range(w)])  # first channel is enough
        prev = line
    return w, h, rows


def ensure_input() -> Path:
    p = DATA / "input" / INPUT_IMAGE
    p.parent.mkdir(parents=True, exist_ok=True)
    write_png(p, 512, 384)
    return p


def output_path(img: dict) -> Path:
    return DATA / img.get("type", "output") / img.get("subfolder", "") / img["filename"]


# --- Commands -------------------------------------------------------------------


def cmd_record_instance(image: str) -> None:
    stats = get("/system_stats")
    insp = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
    print(
        json.dumps(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "comfy_url": COMFY_URL,
                "comfyui_version": stats["system"].get("comfyui_version"),  # type: ignore[index]
                "python_version": stats["system"].get("python_version"),  # type: ignore[index]
                "pytorch_version": stats["system"].get("pytorch_version"),  # type: ignore[index]
                "image": image,
                "image_id": insp["Id"],
                "image_repo_digests": insp.get("RepoDigests", []),
                "image_label_version": (insp["Config"].get("Labels") or {}).get(
                    "org.opencontainers.image.version"
                ),
            },
            indent=2,
        )
    )


def cmd_submit(path: str) -> None:
    """POST a workflow (API format, bare graph or {"prompt": graph}) and wait for it."""
    wf = json.loads(Path(path).read_text())
    status, body = http("POST", "/prompt", wf if "prompt" in wf else {"prompt": wf})
    print(json.dumps(body))
    if status != 200:
        sys.exit(1)
    pid = body["prompt_id"]  # type: ignore[index]
    for _ in range(300):
        entry = history().get(pid)
        if entry and (entry.get("status") or {}).get("completed") is not None:
            print(json.dumps(entry["status"]))
            sys.exit(0 if completed(entry) else 1)
        time.sleep(1)
    sys.exit("timed out waiting for " + pid)


def check_t1() -> str:
    entries = new_entries("T1")
    if not entries:
        raise CheckFailed("no new /history entry since setup")
    reasons = []
    for pid, e in entries.items():
        if not completed(e):
            reasons.append(
                f"{pid[:8]}: not completed successfully ({(e.get('status') or {}).get('status_str')})"
            )
            continue
        if "ImageInvert" not in class_types(e):
            reasons.append(f"{pid[:8]}: graph has no ImageInvert")
            continue
        imgs = [
            i
            for out in e.get("outputs", {}).values()
            for i in out.get("images", [])
            if i.get("type") == "output" and i["filename"].startswith("t1_")
        ]
        if not imgs:
            reasons.append(f"{pid[:8]}: no saved output with prefix t1_")
            continue
        for img in imgs:
            p = output_path(img)
            if not p.is_file():
                reasons.append(f"{pid[:8]}: {p} missing on disk")
                continue
            w, h, rows = read_png(p)
            if (w, h) != (256, 256):
                reasons.append(f"{pid[:8]}: {img['filename']} is {w}x{h}, want 256x256")
                continue
            # The input runs black (left) to white (right); inverted, left is bright.
            if rows:
                left = sum(r[0] for r in rows) / h
                right = sum(r[-1] for r in rows) / h
                if not left > right + 64:
                    reasons.append(
                        f"{pid[:8]}: {img['filename']} is not inverted (left {left:.0f}, right {right:.0f})"
                    )
                    continue
            return f"{pid[:8]} completed; {img['filename']} is 256x256 and inverted"
    raise CheckFailed("; ".join(reasons))


T2_CLASS = "MathExpression|pysssss"
T2_PIN = "aac13aa7ce35b07d43633c3bbe654a38c00d74f5"  # the commit registry 1.2.5 was published from
T2_VERSION = "1.2.5"


def t2_pack_dirs() -> list[Path]:
    root = DATA / "custom_nodes"
    found = []
    for d in root.iterdir() if root.is_dir() else []:
        pp = d / "pyproject.toml"
        if (
            d.is_dir()
            and pp.is_file()
            and 'name = "comfyui-custom-scripts"' in pp.read_text()
        ):
            found.append(d)
    return found


def check_t2() -> str:
    info = get("/object_info")
    if T2_CLASS not in info:  # type: ignore[operator]
        raise CheckFailed(
            f"{T2_CLASS} is not in /object_info (pack not installed, or ComfyUI not restarted)"
        )
    dirs = t2_pack_dirs()
    if not dirs:
        raise CheckFailed("no comfyui-custom-scripts pack on the custom_nodes volume")
    d = dirs[0]
    head_file = d / ".git" / "HEAD"
    if head_file.exists():
        head = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if head != T2_PIN:
            raise CheckFailed(
                f"{d.name} is at {head[:12] or '?'}, want the pinned {T2_PIN[:12]}"
            )
        pinned = f"git {T2_PIN[:8]}"
    else:
        ver = next(
            (
                ln.split("=", 1)[1].strip().strip('"')
                for ln in (d / "pyproject.toml").read_text().splitlines()
                if ln.startswith("version")
            ),
            "?",
        )
        if ver != T2_VERSION:
            raise CheckFailed(
                f"{d.name} is version {ver}, want {T2_VERSION} (commit {T2_PIN[:8]})"
            )
        pinned = f"registry {ver}"
    reasons = []
    for pid, e in new_entries("T2").items():
        if T2_CLASS not in class_types(e):
            continue
        if not completed(e):
            reasons.append(f"{pid[:8]} used {T2_CLASS} but did not complete")
            continue
        vals = [
            v for out in e.get("outputs", {}).values() for v in out.get("value", [])
        ]
        if 42 not in vals:
            reasons.append(
                f"{pid[:8]} completed but produced {vals or 'no value'}, want 42"
            )
            continue
        return f"{T2_CLASS} in /object_info ({d.name}, {pinned}); {pid[:8]} completed with value 42"
    raise CheckFailed("; ".join(reasons) or f"no new /history entry uses {T2_CLASS}")


T3_DIR = HERE / "tasks" / "T3"


def t3_lookup(info: dict, q: dict) -> object:
    node = info[q["node"]]
    if q["kind"] == "output_types":
        return list(node["output"])
    spec = None
    for section in ("required", "optional"):
        if q["input"] in node["input"].get(section, {}):
            spec = node["input"][section][q["input"]]
    if spec is None:
        raise KeyError(f"{q['node']} has no input {q['input']}")
    kind_, opts = spec[0], (spec[1] if len(spec) > 1 else {})
    if q["kind"] == "input_type":
        return "COMBO" if isinstance(kind_, list) else kind_
    if q["kind"] == "options":
        return list(kind_) if isinstance(kind_, list) else list(opts["options"])
    if q["kind"] in ("default", "min", "max", "step"):
        return opts[q["kind"]]
    raise ValueError(q["kind"])


def cmd_derive_t3() -> None:
    src = RESULTS / "object_info.json"
    if not src.exists():
        sys.exit("results/object_info.json missing; run ./groundtruth.sh first")
    info = json.loads(src.read_text())
    meta = json.loads((RESULTS / "object_info.meta.json").read_text())
    questions = json.loads((T3_DIR / "questions.json").read_text())
    answers = {q["id"]: t3_lookup(info, q) for q in questions}
    out = {
        "derived_from": {
            "comfyui_version": meta["comfyui_version"],
            "image_id": meta["image_id"],
        },
        "answers": answers,
    }
    (T3_DIR / "answers.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(answers))


def t3_equal(kind: str, want: object, got: object) -> bool:
    if isinstance(want, (bool, str)):
        return (
            isinstance(got, (str, bool))
            and str(got).strip().lower() == str(want).lower()
        )
    if isinstance(want, (int, float)):
        try:
            return abs(float(got) - float(want)) < 1e-9  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if isinstance(want, list):
        if not isinstance(got, list):
            return False
        norm = [str(x) for x in got]
        # Output order is meaningful (it is the socket index); a set of options is not.
        return (
            norm == [str(x) for x in want]
            if kind == "output_types"
            else sorted(norm) == sorted(map(str, want))
        )
    return got == want


def check_t3() -> str:
    questions = {
        q["id"]: q for q in json.loads((T3_DIR / "questions.json").read_text())
    }
    want = json.loads((T3_DIR / "answers.json").read_text())["answers"]
    p = WORKSPACE / "results" / "T3.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        got = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T3.json is not JSON: {e}") from e
    got = got.get("answers", got) if isinstance(got, dict) else {}
    wrong = [
        f"{qid} (want {want[qid]!r}, got {got.get(qid)!r})"
        for qid in want
        if not t3_equal(questions[qid]["kind"], want[qid], got.get(qid))
    ]
    score = len(want) - len(wrong)
    detail = f"{score}/{len(want)}" + (f"; wrong: {', '.join(wrong)}" if wrong else "")
    if score < 9:
        raise CheckFailed(detail)
    return detail


T4_WORKFLOW = {
    # LoadImage's second output (index 1) is a MASK; SaveImage wants an IMAGE.
    "1": {"class_type": "LoadImage", "inputs": {"image": INPUT_IMAGE}},
    "2": {
        "class_type": "SaveImage",
        "inputs": {"images": ["1", 1], "filename_prefix": "t4_"},
    },
}


def cmd_setup_t4() -> None:
    ensure_input()
    (WORKSPACE / "results").mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "results" / "T4.json").unlink(missing_ok=True)
    (WORKSPACE / "T4-workflow.json").write_text(
        json.dumps(T4_WORKFLOW, indent=2) + "\n"
    )
    status, body = http("POST", "/prompt", {"prompt": T4_WORKFLOW})
    if status == 200:
        sys.exit("the T4 workflow was ACCEPTED; it is supposed to be broken")
    (RESULTS / "T4.expected.json").write_text(
        json.dumps({"http_status": status, "response": body}, indent=2) + "\n"
    )
    print(json.dumps(body))


def norm(s: object) -> str:
    return " ".join(str(s).lower().replace("_", " ").split())


def check_t4() -> str:
    exp = json.loads((RESULTS / "T4.expected.json").read_text())["response"]
    p = WORKSPACE / "results" / "T4.json"
    if not p.exists():
        raise CheckFailed(f"{p} not written")
    try:
        rep = json.loads(p.read_text())
    except ValueError as e:
        raise CheckFailed(f"T4.json is not JSON: {e}") from e
    if rep.get("succeeded") is not False:
        raise CheckFailed(f"report claims success (succeeded={rep.get('succeeded')!r})")
    text = norm(" ".join(str(v) for v in rep.values() if v is not None))
    # The specific error is the per-node one; the top-level message is generic.
    node_id, node_err = next(iter(exp["node_errors"].items()))
    err = node_err["errors"][0]
    # The fault may be named in ComfyUI's words (its per-node error type or
    # message), or in a client's own words for the same fault: both types of
    # the mismatched link plus a mismatch verb. comfy-cli validates before
    # /prompt and says "input 'images' expects IMAGE but LoadImage[1] produces
    # MASK". The generic top-level "Prompt outputs failed validation" names
    # neither, so it does not count.
    extra = err.get("extra_info") or {}
    got_t, want_t = extra.get("received_type"), (extra.get("input_config") or [None])[0]
    if any(norm(s) in text for s in (err["type"], err["message"])):
        wording = f"ComfyUI's {err['type']!r}"
    elif (
        got_t
        and want_t
        and re.search(rf"\b{re.escape(norm(got_t))}\b", text)
        and re.search(rf"\b{re.escape(norm(want_t))}\b", text)
        and re.search(r"mismatch|expect|incompatible", text)
    ):
        wording = f"the {got_t}->{want_t} type mismatch in other words"
    else:
        raise CheckFailed(
            f"report names neither {err['type']!r}/{err['message']!r} "
            f"nor the {got_t}->{want_t} type mismatch"
        )
    if str(rep.get("node_id")) != node_id:
        raise CheckFailed(
            f"report blames node {rep.get('node_id')!r}; ComfyUI rejected node {node_id!r}"
        )
    return f"succeeded=false, node {node_id}, names {wording}"


CHECKS = {"t1": check_t1, "t2": check_t2, "t3": check_t3, "t4": check_t4}


def cmd_check(task: str) -> None:
    try:
        print("PASS " + CHECKS[task]())
    except CheckFailed as e:
        print(f"FAIL {e}")
        sys.exit(1)


COMMANDS = {
    "record-instance": cmd_record_instance,
    "mark": mark,
    "ensure-input": lambda: print(ensure_input()),
    "submit": cmd_submit,
    "derive-t3": cmd_derive_t3,
    "setup-t4": cmd_setup_t4,
    "check": cmd_check,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: harness.py {{{'|'.join(COMMANDS)}}} [args]")
    RESULTS.mkdir(exist_ok=True)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
