"""The `read` profile's docs tools (#134): docs_search and docs_guide.

Both read the corpus built into the image (`corpus.py`), never the network:

    docs_search   FTS5 over docs.comfy.org (Comfy-Org/docs at COMFY_DOCS_SHA)
                  and our guides, section by section
    docs_guide    the guides by topic: skills/comfyui-workflows/, the same
                  markdown the published skill ships

They are separate from the live node and template tools on purpose (#134,
decision B): nothing here merges results with /object_info or /templates.

`tools.py` wraps each entry of DOCS_TOOLS in its ToolSpec.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from .corpus import DOCS_SOURCE, Corpus
from .errors import RelayError
from .tools_introspection import READ, READ_ONLY, _Compact, _invalid_query

if TYPE_CHECKING:
    from .tools import Relay

MAX_TEXT_CHARS = 1500
MAX_QUERY_CHARS = 500
# The distinct words a query searches for, at most. More only slow the FTS query and the excerpting.
MAX_QUERY_WORDS = 16
# Question words that would otherwise have to match too: "how do I add a lora" searches for "add lora".
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i if in is it its me my of on or should the this that "
    "to what when where which why with you your".split()
)


def _query_words(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:[._][a-z0-9]+)*", query.lower())  # keeps sd1.5 and value_not_in_list whole
    words = list(dict.fromkeys(words))  # each word once: repeating one adds nothing but work
    return ([w for w in words if w not in _STOPWORDS] or words)[:MAX_QUERY_WORDS]


def _corpus(relay: Relay) -> Corpus:
    if relay.corpus is None:
        raise RelayError(
            "corpus_unavailable",
            f"this server has no docs corpus ({relay.corpus_error or 'not built'}); the image builds one, a server "
            "run from source has none. Use the live tools: node_describe, template_search.",
        )
    return relay.corpus


class DocHit(_Compact):
    source: str = Field(description="docs.comfy.org, or guides (this project's own, the comfyui-workflows skill)")
    version: str = Field(description="The docs commit SHA, or this project's version for a guide")
    path: str = Field(description="The file in its source repository")
    url: str = Field(description="Where to read it upstream")
    license: str
    title: str = Field(description="The page's title")
    section: str = Field(description="The headings above this section, outermost first; empty for a page's opening")
    text: str = Field(description="The section's markdown, or an excerpt around the match when it is long")
    topic: str | None = Field(default=None, description="A guide's topic: docs_guide(topic) returns all of it")


class DocsSearchResult(_Compact):
    query: str
    searched: list[str] = Field(
        description="The words actually searched for: question words dropped, each word once, at most "
        f"{MAX_QUERY_WORDS}"
    )
    match: Literal["all", "any"] = Field(
        description="all: every result has every query word. any: none did, so these have at least one"
    )
    total_matches: int
    results: list[DocHit]
    note: str | None = Field(
        default=None, description="When any result is from docs.comfy.org: which ComfyUI it describes"
    )
    hint: str | None = Field(default=None, description="When match is any: how to narrow the query")


def _docs_search(relay: Relay) -> Callable[..., Any]:
    async def docs_search(
        query: str = Field(
            min_length=1,
            max_length=MAX_QUERY_CHARS,
            description="Words to find: 'websocket executing message', 'lora strength'",
        ),
        limit: int = Field(default=5, ge=1, le=20),
    ) -> DocsSearchResult:
        """Search the documentation built into this server: docs.comfy.org (Comfy Org's ComfyUI docs: the workflow
        JSON spec, the server's routes and websocket messages, custom node development, tutorials, interface and
        troubleshooting pages, built-in node pages) and this project's own guides (docs_guide).

        Results are sections of pages, best match first, each with its source, version, path, license and upstream
        url, and a guide's with its docs_guide topic. docs.comfy.org describes the latest ComfyUI, which may not
        match the version this server serves: for a node's inputs, defaults and outputs use node_describe, which
        reads the running instance. Words match across word forms (run, running); every word must match unless
        none do.
        """
        words = _query_words(query)
        if not words:
            raise _invalid_query(query)
        # SQLite blocks while it works: in a thread, so a slow query never stalls the other tools.
        hits, total, mode = await asyncio.to_thread(_corpus(relay).search, words, limit, MAX_TEXT_CHARS)
        pin = relay.settings.comfyui_pin
        note = (
            "docs.comfy.org describes the latest ComfyUI, which may not match the ComfyUI this server serves"
            + (f" ({pin})" if pin else "")
            + "; check a node against the instance with node_describe"
        )
        return DocsSearchResult(
            query=query,
            searched=words,
            match=mode,
            total_matches=total,
            results=[DocHit(**hit.__dict__) for hit in hits],
            note=note if any(hit.source == DOCS_SOURCE for hit in hits) else None,
            hint="no section has every word, so these have some of them; search again with fewer, more "
            "distinctive words"
            if mode == "any" and hits
            else None,
        )

    return docs_search


class GuideTopic(BaseModel):
    topic: str
    title: str
    summary: str


class Guide(BaseModel):
    topic: str
    title: str
    path: str = Field(description="The file in this project's repository")
    url: str
    license: str
    version: str
    text: str = Field(description="The guide, as markdown")


class DocsGuideResult(_Compact):
    topics: list[GuideTopic] | None = Field(
        default=None, description="Without a topic: every topic, in the order the guides' index lists them"
    )
    guide: Guide | None = Field(default=None, description="With a topic: that guide")


def _docs_guide(relay: Relay) -> Callable[..., Any]:
    async def docs_guide(
        topic: str | None = Field(default=None, description="A topic from the list; leave it out to list them"),
    ) -> DocsGuideResult:
        """Read this project's curated guides for working with ComfyUI workflows: UI vs API workflow JSON, adding
        models and nodes (propose a manifest change, never install), errors and validation, this server's own
        limits, and authoring comfy.yaml.

        Without a topic it lists the topics with a one-line summary each; with one it returns that guide's
        markdown. They are the published comfyui-workflows skill, so an agent with the skill installed has the
        same text. docs_search searches them together with docs.comfy.org.
        """
        corpus = _corpus(relay)
        listed = await asyncio.to_thread(corpus.topics)
        if topic is None:
            return DocsGuideResult(
                topics=[GuideTopic(**{k: t[k] for k in ("topic", "title", "summary")}) for t in listed]
            )
        found = await asyncio.to_thread(corpus.guide, topic.strip().lower())
        if found is None:
            names = [t["topic"] for t in listed]
            raise RelayError(
                "unknown_topic", f"there is no guide {topic!r}; the topics are: {', '.join(names)}", topics=names
            )
        return DocsGuideResult(guide=Guide(**{k: v for k, v in found.items() if k != "summary"}))

    return docs_guide


DOCS_TOOLS: tuple[tuple[str, frozenset[str], Callable[[Relay], Callable[..., Any]], ToolAnnotations], ...] = (
    ("docs_search", READ, _docs_search, READ_ONLY),
    ("docs_guide", READ, _docs_guide, READ_ONLY),
)
