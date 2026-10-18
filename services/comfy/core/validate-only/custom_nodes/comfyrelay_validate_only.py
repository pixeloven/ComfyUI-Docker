"""A validate-only /prompt for the core images (#215). Off by default: COMFY_ENABLE_VALIDATE_ONLY=true loads it.

ComfyUI (v0.38.0) has no dry run. POST /prompt checks a graph (node replacements, then
execution.validate_prompt) and puts a valid one on the queue, whose worker starts it at once. This module adds
one route beside it:

    POST /comfyrelay/validate_only   takes /prompt's body and answers as /prompt does: 200 {prompt_id, number,
                                     node_errors}, or 400 {error, node_errors}. A graph that passes is never
                                     put on the queue, so nothing runs.
    GET  /comfyrelay/validate_only   {"validate_only": true, "version": 1}, for a client to detect it.

The POST runs ComfyUI's own /prompt handler, found in its route table, with a context variable set, and
PromptQueue.put, wrapped, drops what it is handed while that variable is set. So the checks are ComfyUI's, not
a copy, and every other prompt is queued as usual. A ComfyUI without this module has no such route and answers
404 or 405: a validate request can never be queued by mistake.

It is first-party, defines no node class, and loads from the image, not from the custom_nodes volume:
startup.sh adds /opt/comfyui-docker/validate-only/extra_model_paths.yaml, whose only entry is this directory.
It goes when ComfyUI's /prompt gets a validate-only flag of its own (the upstream ask: #234, for #215).

tests/relay/corpus.sh mounts this file into a published core-cpu's /app/custom_nodes instead, so the corpus
exercises it on every ComfyUI bump.
"""

import contextvars
import logging

import execution
from aiohttp import web
from server import PromptServer

PATH = "/comfyrelay/validate_only"
VERSION = 1
_validating = contextvars.ContextVar("comfyrelay_validate_only", default=False)


def _install() -> None:
    routes = PromptServer.instance.routes
    post_prompt = next(
        (r.handler for r in routes if isinstance(r, web.RouteDef) and r.method == "POST" and r.path == "/prompt"),
        None,
    )
    if post_prompt is None:
        logging.error("comfyrelay_validate_only: ComfyUI's POST /prompt handler wasn't found; %s is not served", PATH)
        return

    put = execution.PromptQueue.put

    def put_unless_validating(self, item):
        # Called from ComfyUI's /prompt handler, in the request's task: the variable is set only under PATH.
        if _validating.get():
            return None
        return put(self, item)

    execution.PromptQueue.put = put_unless_validating

    @routes.get(PATH)
    async def validate_only_info(request):
        return web.json_response({"validate_only": True, "version": VERSION})

    @routes.post(PATH)
    async def validate_only(request):
        token = _validating.set(True)
        try:
            return await post_prompt(request)
        finally:
            _validating.reset(token)

    logging.info(
        "comfyrelay_validate_only: installed; POST %s checks a prompt as /prompt does and never queues it", PATH
    )


_install()

NODE_CLASS_MAPPINGS = {}
