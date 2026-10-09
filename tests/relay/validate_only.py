"""A ComfyUI custom node for tests/relay/corpus.sh only, never in an image: it lets the corpus have ComfyUI
validate a graph without running it.

ComfyUI (v0.38.0) has no dry run. POST /prompt checks a graph (node replacements, then
execution.validate_prompt) and puts a valid one on the queue, whose worker starts it at once, so clearing the
queue afterwards races the worker. With this loaded, /prompt still checks every graph exactly as it always does
and answers as it always does, but a graph sent with extra_data {"comfyrelay_validate_only": true} is never put
on the queue, so nothing runs. Every other prompt is queued as usual.

    -v tests/relay/validate_only.py:/app/custom_nodes/comfyrelay_validate_only.py:ro
"""

import logging

import execution

MARK = "comfyrelay_validate_only"
_put = execution.PromptQueue.put


def _put_unless_validate_only(self, item):
    # item is (number, prompt_id, prompt, extra_data, outputs_to_execute, sensitive), as server.py's post_prompt
    # builds it.
    if isinstance(item[3], dict) and item[3].get(MARK):
        return
    return _put(self, item)


execution.PromptQueue.put = _put_unless_validate_only
logging.info("comfyrelay_validate_only: installed; prompts marked %s are validated and never queued", MARK)

NODE_CLASS_MAPPINGS = {}
