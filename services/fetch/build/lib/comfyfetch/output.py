"""How results reach a human, a log, or a machine.

Three consumers with different needs, and one flag:

- a person at a terminal wants progress and colour;
- a Kubernetes Job wants plain lines a log aggregator can read, with no
  escape codes and no progress bars redrawing a thousand times;
- automation and agents want JSON with stable keys.

`auto` picks plain when stdout is not a TTY, which is the case in every CI job
and every container, so the useful default needs no flag.

Everything human-facing goes to STDERR. Stdout carries the artifact -- a lock
document, or JSON -- so `comfyfetch resolve ... > lock.yaml` stays correct.
"""

from __future__ import annotations

import enum
import json
import sys
from typing import Any

from rich.console import Console


class Mode(str, enum.Enum):
    auto = "auto"
    plain = "plain"
    json = "json"


class Out:
    def __init__(self, mode: Mode = Mode.auto) -> None:
        if mode is Mode.auto:
            mode = Mode.plain if not sys.stdout.isatty() else Mode.auto
        self.mode = mode
        self._console = Console(stderr=True, no_color=mode is Mode.plain,
                                highlight=mode is not Mode.plain)

    @property
    def is_json(self) -> bool:
        return self.mode is Mode.json

    def note(self, message: str) -> None:
        """Progress. Suppressed entirely in json mode so stdout stays parseable."""
        if not self.is_json:
            self._console.print(message)

    def problem(self, message: str) -> None:
        if not self.is_json:
            self._console.print(f"[red]{message}[/red]" if self.mode is Mode.auto
                                else message)

    def result(self, human: str, machine: dict[str, Any]) -> None:
        """The outcome, in whichever form the caller asked for."""
        if self.is_json:
            json.dump(machine, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            self._console.print(human)
