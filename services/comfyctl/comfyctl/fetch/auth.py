"""Host-keyed credential lookup.

The manifest and the lock carry the same `auth` map — host to an `${ENV_VAR}`
reference, never a literal, because the schema rejects literals so a token
cannot be committed. Credentials resolve by the URL's HOST, which is why no
model entry carries an auth field and `models[]` stays exactly comfy-cli's
documented shape.
"""

from __future__ import annotations

import os
import re
import urllib.parse

_ENV_REF = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")


class AuthMap:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._by_host: dict[str, str] = {}
        for host, ref in (mapping or {}).items():
            m = _ENV_REF.match(str(ref))
            if m:
                self._by_host[host] = m.group(1)

    @classmethod
    def from_document(cls, doc: dict | None) -> AuthMap:
        return cls((doc or {}).get("auth") or {})

    @staticmethod
    def host_of(url: str) -> str:
        return (urllib.parse.urlsplit(url).hostname or "").lower()

    def var_for(self, url: str) -> str | None:
        return self._by_host.get(self.host_of(url))

    def token_for(self, url: str) -> str | None:
        """The token for this URL's host, or None."""
        var = self.var_for(url)
        return os.environ.get(var) if var else None

    def missing_var_for(self, url: str) -> str | None:
        """The variable a host declares but does not have set.

        Not a blocking condition: most HuggingFace files are public, and
        refusing them because HF_TOKEN happens to be unset would be wrong. It is
        reported only when a fetch then fails — the case a bare "sha256
        mismatch" would otherwise misattribute, since an unauthenticated Civitai
        request returns an HTML error page with HTTP 200.
        """
        var = self.var_for(url)
        return var if var and not os.environ.get(var) else None
