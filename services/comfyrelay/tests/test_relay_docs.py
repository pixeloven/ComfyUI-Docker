"""The docs corpus (#134): the MDX conversion and snippet inlining, what each row carries, what the build ships
beside the index, and the shapes of docs_search, docs_guide and server_info.corpus."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from comfyrelay.corpus import docs_pages, mdx_to_markdown, sections
from comfyrelay.server import build_server
from mcp import Client
from relay_helpers import DOCS_FILES, DOCS_SHA, comfyui_answering, settings

pytestmark = pytest.mark.anyio

# -- MDX to markdown ------------------------------------------------------------------


def test_front_matter_becomes_fields_and_leaves_the_body():
    page = mdx_to_markdown('---\ntitle: "Routes"\ndescription: The server\'s routes.\nicon: "route"\n---\nBody.\n')
    assert (page.title, page.description, page.body) == ("Routes", "The server's routes.", "Body.\n")


def test_imports_jsx_and_media_go_but_their_text_and_code_stay():
    page = mdx_to_markdown(
        """import { Foo } from "/components/foo.jsx";
export const meta = {};

<Tabs>
  <Tab title="Local users">
    Update ComfyUI first.
  </Tab>
</Tabs>
<ParamField body="prompt_id" type="string" required>
The id of the prompt.
</ParamField>
<img src="/images/a.png" alt="a" />
<video controls>
  <source src="/images/a.mp4" />
  The fallback text of a video.
</video>
![a screenshot](/images/b.png)
<Frame><img src="/images/c.png" /></Frame>
Replace <your-api-key>, and see `<ComfyUI>/models` and <a href="/x">the models page</a>.
{/* an MDX comment */}

```python
import json
from x import y
<not a tag>
```
"""
    )
    body = page.body
    for gone in (
        "import {",
        "export const",
        "<Tab",
        "</Tab",
        "<ParamField",
        "<img",
        "video",
        "fallback",
        "![",
        ".png",
        "<Frame",
        "comment",
        "<a ",
    ):
        assert gone not in body, gone
    for kept in (
        "Local users",
        "Update ComfyUI first.",
        "prompt_id string",
        "The id of the prompt.",
        "Replace <your-api-key>",
        "`<ComfyUI>/models`",
        "the models page",
        "```python\nimport json\nfrom x import y\n<not a tag>\n```",
    ):
        assert kept in body, kept


def test_a_snippet_is_inlined_where_it_is_used_and_nested_snippets_too():
    docs = {
        "/snippets/outer.mdx": 'import Inner from "/snippets/inner.mdx";\n<Warning>Outer text.</Warning>\n<Inner/>\n',
        "/snippets/inner.mdx": "Inner text.\n",
    }

    def read(ref: str) -> str:
        if ref not in docs:
            raise FileNotFoundError(ref)
        return docs[ref]

    page = mdx_to_markdown(
        'import Outer from "/snippets/outer.mdx";\nimport Gone from "/snippets/missing.mdx";\n\nBefore.\n\n<Outer />\n'
        "<Gone />\nAfter.\n",
        read,
    )
    assert page.body.index("Before.") < page.body.index("Outer text.") < page.body.index("Inner text.")
    assert page.body.index("Inner text.") < page.body.index("After.")
    assert "import" not in page.body and "<" not in page.body
    assert page.snippets == {"snippets/outer.mdx", "snippets/inner.mdx"}


def test_sections_split_at_headings_outside_code_and_keep_the_trail():
    got = sections(
        "Intro.\n\n## Routes\n\n### Built in\n\nText.\n\n```sh\n# not a heading\n```\n\n## Messages\nMore.\n\n"
        "## Run a `node\\_id` {#run it}\nLast.\n"
    )
    assert [(s.heading, s.anchor) for s in got] == [
        ("", ""),
        ("Routes › Built in", "built-in"),  # "Routes" has no text of its own, so it folds into the next
        ("Messages", "messages"),
        ("Run a node_id", "run-it"),  # an explicit anchor wins
    ]
    assert "# not a heading" in got[1].text


def test_the_page_list_is_the_english_navigation_without_openapi_operations():
    pages, operations = docs_pages(json.loads(DOCS_FILES["docs.json"]))
    assert pages == ["development/server/messages", "built-in-nodes/Video Slice"]
    assert operations == ["GET /nodes"]


# -- the build ------------------------------------------------------------------------


def rows(corpus_path: str) -> list[dict]:
    db = sqlite3.connect(corpus_path)
    db.row_factory = sqlite3.Row
    return [dict(r) for r in db.execute("SELECT * FROM docs")]


def test_every_row_carries_source_version_path_license_and_url(corpus_path):
    got = rows(corpus_path)
    docs = [r for r in got if r["source"] == "docs.comfy.org"]
    guides = [r for r in got if r["source"] == "guides"]
    assert {(r["path"], r["version"], r["license"]) for r in docs} == {
        ("development/server/messages.mdx", DOCS_SHA, "GPL-3.0"),
        ("built-in-nodes/Video Slice.mdx", DOCS_SHA, "GPL-3.0"),
    }
    assert {r["url"] for r in docs} == {
        "https://docs.comfy.org/development/server/messages",
        "https://docs.comfy.org/development/server/messages#built-in-message-types",
        "https://docs.comfy.org/built-in-nodes/Video%20Slice",
    }
    assert {(r["path"], r["version"], r["license"]) for r in guides} == {
        ("skills/comfyui-workflows/references/workflow-formats.md", "9.9.9", "MIT"),
        ("skills/comfy-manifest/SKILL.md", "9.9.9", "MIT"),
    }
    assert all(r["url"].startswith("https://github.com/pixeloven/ComfyUI-Docker/blob/v9.9.9/skills/") for r in guides)
    assert not any("quasar" in r["body"] for r in got), "an unlisted page or a translation was indexed"


def test_the_build_ships_the_indexed_source_the_license_and_a_notice(corpus_path):
    out = Path(corpus_path).parent
    shipped = sorted(p.relative_to(out / "source").as_posix() for p in (out / "source").rglob("*") if p.is_file())
    assert shipped == [
        "built-in-nodes/Video Slice.mdx",
        "development/server/messages.mdx",
        "snippets/inner.mdx",
        "snippets/reminder.mdx",
    ]
    assert (out / "source/development/server/messages.mdx").read_text() == DOCS_FILES["development/server/messages.mdx"]
    assert (out / "GPL-3.0.txt").read_text() == DOCS_FILES["LICENSE"]
    notice = (out / "NOTICE").read_text()
    for needed in (
        "https://github.com/Comfy-Org/docs",
        DOCS_SHA,
        "GNU General Public License, version 3 (GPL-3.0)",
        "Modified on 20",
        "services/comfyrelay/comfyrelay/corpus.py",
        "/blob/v9.9.9/services/comfyrelay/comfyrelay/corpus.py",
        "© Comfy Org. Not affiliated with or endorsed by Comfy Org.",
    ):
        assert needed in notice, needed


# -- the tools --------------------------------------------------------------------------


async def call(tool: str, args: dict, corpus: str | None) -> tuple[bool, dict | str]:
    s = settings(corpus_path=corpus) if corpus else settings()
    server, _ = build_server(s, comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools[tool].annotations.read_only_hint is True and tools[tool].output_schema is not None
        result = await client.call_tool(tool, args)
    if result.is_error:
        text = result.content[0].text
        return False, json.loads(text[text.index("{") :])["error"]
    return True, result.structured_content


async def test_docs_search_returns_attributed_sections_and_says_the_site_is_latest(corpus_path):
    ok, got = await call("docs_search", {"query": "websocket executing"}, corpus_path)
    assert ok, got
    (hit,) = got["results"]
    assert (got["match"], got["total_matches"]) == ("all", 1)
    assert {k: hit[k] for k in ("source", "version", "path", "license", "url", "title", "section")} == {
        "source": "docs.comfy.org",
        "version": DOCS_SHA,
        "path": "development/server/messages.mdx",
        "license": "GPL-3.0",
        "url": "https://docs.comfy.org/development/server/messages#built-in-message-types",
        "title": "Server Messages",
        "section": "Built in message types",
    }
    assert "`executing`" in hit["text"]
    assert "latest ComfyUI" in hit["note"] and "v0.37.0" in hit["note"]


async def test_a_guide_hit_has_no_latest_note_and_no_word_in_common_falls_back_to_any(corpus_path):
    ok, got = await call("docs_search", {"query": "how does template_get differ, zebra?"}, corpus_path)
    assert ok, got
    assert got["match"] == "any"
    assert [(h["source"], h["license"]) for h in got["results"]] == [("guides", "MIT")]
    assert "note" not in got["results"][0]


async def test_docs_search_refuses_a_query_with_nothing_to_search(corpus_path):
    ok, err = await call("docs_search", {"query": "?!"}, corpus_path)
    assert (ok, err["code"]) == (False, "invalid_query")


async def test_docs_guide_lists_topics_and_returns_one(corpus_path):
    ok, listing = await call("docs_guide", {}, corpus_path)
    assert ok and "guide" not in listing
    assert [(t["topic"], t["title"]) for t in listing["topics"]] == [
        ("workflow-formats", "Workflow formats"),
        ("comfy-manifest", "Authoring comfy.yaml"),
    ]
    assert [t["summary"] for t in listing["topics"]] == ["UI vs API.", "the manifest."]  # from the index's list
    ok, got = await call("docs_guide", {"topic": "comfy-manifest"}, corpus_path)
    assert ok and "topics" not in got
    assert {k: got["guide"][k] for k in ("topic", "path", "license", "version")} == {
        "topic": "comfy-manifest",
        "path": "skills/comfy-manifest/SKILL.md",
        "license": "MIT",
        "version": "9.9.9",
    }
    assert got["guide"]["text"].startswith("# Authoring comfy.yaml")


async def test_docs_guide_names_the_topics_for_an_unknown_one(corpus_path):
    ok, err = await call("docs_guide", {"topic": "nope"}, corpus_path)
    assert (ok, err["code"], err["topics"]) == (False, "unknown_topic", ["workflow-formats", "comfy-manifest"])


@pytest.mark.parametrize(("tool", "args"), [("docs_search", {"query": "x"}), ("docs_guide", {})])
async def test_without_a_corpus_the_docs_tools_say_so(tool, args):
    ok, err = await call(tool, args, None)
    assert (ok, err["code"]) == (False, "corpus_unavailable")
    assert "no corpus at /nonexistent/corpus.sqlite" in err["message"]


async def server_info(corpus: str | None) -> dict:
    server, _ = build_server(settings(corpus_path=corpus) if corpus else settings(), comfyui=comfyui_answering())
    async with Client(server, mode="legacy") as client:
        return (await client.call_tool("server_info", {})).structured_content["corpus"]


async def test_server_info_reports_the_corpus_sources_versions_licenses_and_pages(corpus_path):
    got = await server_info(corpus_path)
    assert (got["status"], got["pages"]) == ("built", 4)
    assert [(s["name"], s["version"], s["license"], s["pages"]) for s in got["sources"]] == [
        ("docs.comfy.org", DOCS_SHA, "GPL-3.0", 2),
        ("guides", "9.9.9", "MIT", 2),
    ]
    assert got["sources"][0]["repo"] == "https://github.com/Comfy-Org/docs"
    assert await server_info(None) == {
        "status": "absent",
        "sources": [],
        "reason": "no corpus at /nonexistent/corpus.sqlite",
    }
