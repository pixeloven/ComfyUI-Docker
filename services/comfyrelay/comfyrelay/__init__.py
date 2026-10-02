"""comfyrelay: an MCP sidecar for one ComfyUI instance.

One server per ComfyUI, reached over streamable HTTP with a token, exposing
tools grouped into capability profiles (read, run, manage). The
command is `comfyctl relay`; this package is what that group mounts.
"""

import importlib.metadata

__version__ = importlib.metadata.version("comfyrelay")
