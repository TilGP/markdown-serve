"""Python documentation via the stdlib AST. Each ``.py`` file is one unit."""

from __future__ import annotations

import ast
from pathlib import Path

from markdown_serve.codedoc.base import ToolCheck, ToolStatus
from markdown_serve.codedoc.model import FileDoc, Symbol, Unit
from markdown_serve.project_config import make_ignore

PY_SUFFIXES = {".py"}


class PythonBackend:
    name = "python"
    suffixes = PY_SUFFIXES

    def check(self, root: Path, cfg: dict) -> ToolStatus:
        check = ToolCheck("ast", True, "stdlib (no extra install)")
        return ToolStatus(available=True, notes=[f"{check.name}: {check.hint}"], checks=[check])

    def discover(self, root: Path, cfg: dict, is_ignored) -> list[Unit]:
        root = root.resolve()
        units: list[Unit] = []
        for path in sorted(root.rglob("*.py")):
            if not path.is_file():
                continue
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if is_ignored(rel):
                continue
            units.append(Unit(language="python", rel=rel, source=str(path.resolve()), directory=str(path.parent)))
        return units

    def extra_units(self, root, cfg, is_ignored, units, documented) -> list[Unit]:
        return []

    def document_unit(self, unit: Unit, root: Path, is_ignored) -> list[FileDoc]:
        return [_parse_file(Path(unit.source), unit.rel, root.resolve())]


def document_python_unit(payload: dict) -> dict:
    """Picklable worker. One module in, one FileDoc out."""
    rel = payload.get("rel", "")
    try:
        root = Path(payload["root"])
        ignored = make_ignore(
            payload.get("ignore") or [],
            cache_dir=payload.get("cache_dir") or ".cache/markdown-serve",
            skip_dirs=payload.get("skip_dirs") or [],
        )
        if ignored(rel):
            return {"key": payload.get("key"), "rel": rel, "docs": [], "error": None}
        doc = _parse_file(Path(payload["source"]), rel, root)
        from dataclasses import asdict

        return {"key": payload["key"], "rel": rel, "docs": [asdict(doc)], "error": None}
    except Exception as exc:
        return {"key": payload.get("key"), "rel": rel, "docs": [], "error": f"{rel}: {exc}"}


def _parse_file(path: Path, rel: str, root: Path) -> FileDoc:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"{rel}: {exc}") from exc
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return FileDoc(rel_path=rel, language="python", file_doc=f"Could not parse: {exc.msg}")
    module = _module_name(rel)
    symbols = [
        _symbol(node, rel, module, "")
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return FileDoc(
        rel_path=rel,
        language="python",
        file_doc=ast.get_docstring(tree) or "",
        symbols=symbols,
        includes=_imports(tree, root, rel),
    )


def _module_name(rel: str) -> str:
    path = rel[:-3] if rel.endswith(".py") else rel
    if path.endswith("/__init__"):
        path = path[: -len("/__init__")]
    elif path == "__init__":
        path = ""
    return path.replace("/", ".")


def _symbol(node: ast.AST, rel: str, module: str, parent: str) -> Symbol:
    name = getattr(node, "name", "")
    qualified = ".".join(part for part in (module, parent, name) if part)
    kind = "class" if isinstance(node, ast.ClassDef) else "method" if parent else "function"
    doc = ast.get_docstring(node) or ""
    brief = next((line.strip() for line in doc.splitlines() if line.strip()), "")
    owner = name if not parent else f"{parent}.{name}"
    children = [
        _symbol(child, rel, module, owner)
        for child in getattr(node, "body", [])
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ] if isinstance(node, ast.ClassDef) else []
    return Symbol(
        kind=kind,
        name=name,
        qualified_name=qualified,
        signature=_signature(node),
        doc=doc,
        brief=brief,
        file=rel,
        line=getattr(node, "lineno", 0) or 0,
        end_line=getattr(node, "end_lineno", 0) or 0,
        access="",
        usr=f"py:{qualified}:{getattr(node, 'lineno', 0)}",
        children=children,
    )


def _signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        parts = [ast.unparse(base) for base in node.bases]
        parts += [
            f"{kw.arg}={ast.unparse(kw.value)}" if kw.arg else ast.unparse(kw.value) for kw in node.keywords
        ]
        base = f"({', '.join(parts)})" if parts else ""
        return _decorators(node) + f"class {node.name}{base}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ""
    returns = ""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
        returns = f" -> {ast.unparse(node.returns)}"
    return _decorators(node) + f"{prefix} {node.name}({args}){returns}"


def _decorators(node: ast.AST) -> str:
    lines = [f"@{ast.unparse(dec)}" for dec in getattr(node, "decorator_list", [])]
    return ("\n".join(lines) + "\n") if lines else ""


def _imports(tree: ast.AST, root: Path, rel: str) -> list[str]:
    found: list[str] = []

    def add(module: str, level: int) -> None:
        target = _resolve_module(root, rel, module, level)
        if target and target not in found and target != rel:
            found.append(target)

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, 0)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                add(node.module, node.level)
                for alias in node.names:
                    add(f"{node.module}.{alias.name}", node.level)
            else:
                for alias in node.names:
                    add(alias.name, node.level)
    return found


def _resolve_module(root: Path, rel: str, module: str, level: int) -> str | None:
    if level:
        parts = [part for part in Path(rel).parent.parts if part not in {"", "."}]
        keep = len(parts) - (level - 1)
        if keep < 0:
            return None
        base = parts[:keep]
        dotted = ".".join([*base, *module.split(".")] if module else base)
    else:
        dotted = module
    if not dotted:
        return None
    bits = dotted.split(".")
    candidates = [
        Path(*bits).with_suffix(".py"),
        Path(*bits) / "__init__.py",
        Path("src", *bits).with_suffix(".py"),
        Path("src", *bits) / "__init__.py",
    ]
    hits = [item.as_posix() for item in candidates if (root / item).is_file()]
    return hits[0] if len(hits) == 1 else None
