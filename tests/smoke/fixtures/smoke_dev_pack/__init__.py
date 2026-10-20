# A node pack for tests/smoke/run.sh, which bind-mounts this directory at
# /app/custom_nodes/smoke_dev_pack, the way a developer mounts a pack's source
# (#180), and checks that its node class reaches /object_info. One V1 node, no
# dependencies and no web directory.


class SmokeDevPackEcho:
    CATEGORY = "smoke"
    RETURN_TYPES = ("STRING",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"default": ""})}}

    def run(self, text):
        return (text,)


NODE_CLASS_MAPPINGS = {"SmokeDevPackEcho": SmokeDevPackEcho}
