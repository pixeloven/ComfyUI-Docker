"""A V3 node pack for tests/node-pack/run.sh, the node-pack template's test.

run.sh edits SUFFIX and checks that the restarted ComfyUI runs the new code.
"""

from comfy_api.latest import ComfyExtension, io

SUFFIX = "-v1"
WEB_DIRECTORY = "./web"


class DevCheckEcho(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DevCheckEcho",
            display_name="Dev check: echo",
            category="dev_check",
            inputs=[io.String.Input("text")],
            outputs=[io.String.Output()],
        )

    @classmethod
    def execute(cls, text):
        return io.NodeOutput(text + SUFFIX)


class DevCheckExtension(ComfyExtension):
    async def get_node_list(self):
        return [DevCheckEcho]


async def comfy_entrypoint():
    return DevCheckExtension()
