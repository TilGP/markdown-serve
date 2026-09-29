"""Backend interface. One implementation per language; the builder only sees this."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from markdown_serve.codedoc.model import FileDoc, Unit


@dataclass
class ToolCheck:
    name: str
    ok: bool
    hint: str


@dataclass
class ToolStatus:
    available: bool
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: list[ToolCheck] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "missing": list(self.missing),
            "notes": list(self.notes),
            "checks": [
                {"name": check.name, "ok": check.ok, "hint": check.hint} for check in self.checks
            ],
        }


class LanguageBackend(Protocol):
    name: str
    suffixes: set[str]

    def check(self, root: Path, cfg: dict) -> ToolStatus: ...

    def discover(self, root: Path, cfg: dict, is_ignored) -> list[Unit]: ...

    def document_unit(self, unit: Unit, root: Path, is_ignored) -> list[FileDoc]: ...

    def extra_units(
        self,
        root: Path,
        cfg: dict,
        is_ignored,
        units: list[Unit],
        documented: set[str],
    ) -> list[Unit]: ...
