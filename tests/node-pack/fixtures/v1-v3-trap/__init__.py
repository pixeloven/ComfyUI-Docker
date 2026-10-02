"""A pack that converted to V3 but kept its V1 mappings.

ComfyUI loads NODE_CLASS_MAPPINGS and never calls comfy_entrypoint, so
DevCheckEcho (V3) is missing and nothing is logged about it.
"""

from comfy_api.latest import ComfyExtension, io


class DevCheckLegacy:
    CATEGORY = "dev_check"
    RETURN_TYPES = ("STRING",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {})}}

    def run(self, text):
        return (text,)


NODE_CLASS_MAPPINGS = {"DevCheckLegacy": DevCheckLegacy}


class DevCheckEcho(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="DevCheckEcho",
            category="dev_check",
            inputs=[io.String.Input("text")],
            outputs=[io.String.Output()],
        )

    @classmethod
    def execute(cls, text):
        return io.NodeOutput(text)


class DevCheckExtension(ComfyExtension):
    async def get_node_list(self):
        return [DevCheckEcho]


async def comfy_entrypoint():
    return DevCheckExtension()
