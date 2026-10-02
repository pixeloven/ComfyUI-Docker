"""The good fixture with an import error: there is no module .nodes."""

from comfy_api.latest import ComfyExtension

from .nodes import DevCheckEcho


class DevCheckExtension(ComfyExtension):
    async def get_node_list(self):
        return [DevCheckEcho]


async def comfy_entrypoint():
    return DevCheckExtension()
