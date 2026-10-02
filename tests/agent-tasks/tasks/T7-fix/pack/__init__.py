"""Text nodes for the harness: T7Reverse reverses a string, T7Show displays one."""

from comfy_api.latest import ComfyExtension, io, ui

from .util import reverse_text


class T7Reverse(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="T7Reverse",
            display_name="Reverse text",
            category="t7",
            inputs=[io.String.Input("text")],
            outputs=[io.Int.Output()],
        )

    @classmethod
    def execute(cls, text):
        return io.NodeOutput(reverse_text(text))


class T7Show(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="T7Show",
            display_name="Show text",
            category="t7",
            is_output_node=True,
            inputs=[io.String.Input("text", force_input=True)],
            outputs=[],
        )

    @classmethod
    def execute(cls, text):
        return io.NodeOutput(ui=ui.PreviewText(text))


class T7Extension(ComfyExtension):
    async def get_node_list(self):
        return [T7Reverse, T7Show]


async def comfy_entrypoint():
    return T7Extension()
