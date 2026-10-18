"""A validate-only /prompt for the core images (#215). Off by default: COMFY_ENABLE_VALIDATE_ONLY=true loads it.

ComfyUI (v0.38.0) has no dry run. POST /prompt checks a graph (node replacements, then
execution.validate_prompt) and puts a valid one on the queue, whose worker starts it at once. This module adds
one route beside it (and, as for every route, at /api/comfyrelay/validate_only):

    POST /comfyrelay/validate_only   takes /prompt's body and answers as /prompt does: 200 {prompt_id, number,
                                     node_errors}, or 400 {error, node_errors}. A graph that passes is never
                                     put on the queue, so nothing runs. 503 {error: {type: validate_only_unsafe,
                                     message}, node_errors: {}} when that can't be guaranteed (below).
    GET  /comfyrelay/validate_only   {"validate_only": true, "version": 1}, for a client to detect it.

The POST runs ComfyUI's own /prompt handler, found in its route table, with a context variable set, and
PromptQueue.put, wrapped at the class, drops what it is handed while that variable is set. So the checks are
ComfyUI's, not a copy, and every other prompt is queued as usual. A ComfyUI without this module has no such
route and answers 404 or 405.

It fails closed. A custom node can replace put on the queue itself (prompt_queue.put = ...), which shadows the
class's, or wrap the class's again; either way the drop might not run. So each POST first checks that the queue
has no put of its own and that its class's put is still this module's wrapper, and answers 503 otherwise,
without running the handler.

Loading it twice (the image's opt-in plus a copy on the custom_nodes volume) installs it once: the second load
finds the marker on PromptServer.instance and does nothing.

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
MARKER = "_comfyrelay_validate_only"
_validating = contextvars.ContextVar("comfyrelay_validate_only", default=False)


def _install() -> None:
    server = PromptServer.instance
    routes = server.routes
    if getattr(server, MARKER, None) is not None or any(getattr(r, "path", None) == PATH for r in routes):
        logging.info("comfyrelay_validate_only: already installed; this copy does nothing")
        return
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

    def drop_is_in_force() -> bool:
        queue = server.prompt_queue
        return "put" not in vars(queue) and type(queue).put is put_unless_validating

    execution.PromptQueue.put = put_unless_validating
    setattr(server, MARKER, VERSION)

    @routes.get(PATH)
    async def validate_only_info(request):
        return web.json_response({"validate_only": True, "version": VERSION})

    @routes.post(PATH)
    async def validate_only(request):
        if not drop_is_in_force():
            logging.warning("comfyrelay_validate_only: refused; another custom node replaced PromptQueue.put")
            error = {
                "type": "validate_only_unsafe",
                "message": "another custom node replaced PromptQueue.put, so a validate-only request could be "
                "queued; refused",
            }
            return web.json_response({"error": error, "node_errors": {}}, status=503)
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
