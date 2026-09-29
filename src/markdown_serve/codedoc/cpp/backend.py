"""C++ documentation via libclang and compile_commands.json."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from markdown_serve.codedoc.base import ToolCheck, ToolStatus
from markdown_serve.codedoc.cpp.compile_commands import load_units
from markdown_serve.codedoc.markdown import doxygen_to_markdown, strip_comment_markers
from markdown_serve.codedoc.model import FileDoc, Symbol, Unit

CPP_SUFFIXES = {".hpp", ".h", ".hh", ".hxx", ".cpp", ".cc", ".cxx", ".ipp", ".inl"}
HEADER_SUFFIXES = {".hpp", ".h", ".hh", ".hxx", ".ipp", ".inl"}

_LIBCLANG: str | None = None


def find_libclang(explicit: str | None = None) -> str | None:
    """config path, then ``$LIBCLANG_PATH``, then the system, then the ``libclang`` wheel."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("LIBCLANG_PATH")
    if env:
        candidates.append(Path(env))
    llvm = shutil.which("llvm-config")
    if llvm:
        try:
            libdir = subprocess.check_output([llvm, "--libdir"], text=True, timeout=10).strip()
        except (OSError, subprocess.TimeoutExpired):
            libdir = ""
        if libdir:
            candidates.append(Path(libdir))
    candidates.extend(
        [
            Path("/usr/local/lib/libclang.so"),
            Path("/usr/lib/libclang.so"),
            *sorted(Path("/usr/lib").glob("llvm-*/lib/libclang.so")),
            *sorted(Path("/usr/lib").glob("llvm-*/lib/libclang.dylib")),
            Path("/usr/local/lib/libclang.dylib"),
        ]
    )
    found = _first_library(candidates)
    if found:
        return found
    try:
        import clang.native
    except ImportError:
        return None
    bundled = Path(clang.native.__file__).resolve().parent / "libclang.so"
    if not bundled.is_file():
        bundled = bundled.with_suffix(".dylib")
    return str(bundled) if bundled.is_file() else None


def _first_library(candidates: list[Path]) -> str | None:
    names = ("libclang.so", "libclang.dylib", "libclang.dll")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
        if candidate.is_dir():
            for name in names:
                path = candidate / name
                if path.is_file():
                    return str(path)
    return None


def configure_libclang(explicit: str | None = None) -> str:
    """Point the bindings at a library. Safe to call once per process."""
    global _LIBCLANG
    path = find_libclang(explicit)
    if not path:
        raise RuntimeError("libclang shared library not found")
    if _LIBCLANG != path:
        from clang.cindex import Config

        Config.set_library_file(path)
        _LIBCLANG = path
    return path


def clang_bindings_available() -> bool:
    try:
        import clang.cindex  # noqa: F401
    except ImportError:
        return False
    return True


class CppBackend:
    name = "cpp"
    suffixes = set(CPP_SUFFIXES)

    def check(self, root: Path, cfg: dict) -> ToolStatus:
        cpp = cfg["codedoc"]["cpp"]
        checks: list[ToolCheck] = []
        bindings = clang_bindings_available()
        checks.append(
            ToolCheck(
                "clang.cindex",
                bindings,
                "installed" if bindings else "uv sync --extra cpp",
            )
        )
        lib = find_libclang(cpp.get("libclang")) if bindings else None
        checks.append(
            ToolCheck(
                "libclang",
                bool(lib),
                lib or "system libclang.so or the libclang wheel (uv sync --extra cpp)",
            )
        )
        commands = root / cpp["compile_commands"]
        checks.append(
            ToolCheck(
                "compile_commands.json",
                commands.is_file(),
                str(commands) if commands.is_file() else f"missing {commands} (cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON)",
            )
        )
        clangxx = shutil.which("clang++")
        checks.append(
            ToolCheck(
                "clang++",
                bool(clangxx),
                clangxx or "optional, used for -print-resource-dir; the compiler in compile_commands.json is enough when it runs",
            )
        )
        required = [check for check in checks if check.name != "clang++"]
        missing = [f"{check.name}: {check.hint}" for check in required if not check.ok]
        notes = [f"{check.name}: {check.hint}" for check in checks if check.ok]
        return ToolStatus(
            available=not missing,
            missing=missing,
            notes=notes,
            checks=checks,
        )

    def discover(self, root: Path, cfg: dict, is_ignored) -> list[Unit]:
        commands = root / cfg["codedoc"]["cpp"]["compile_commands"]
        return load_units(root, commands, is_ignored)

    def extra_units(self, root, cfg, is_ignored, units: list[Unit], documented: set[str]) -> list[Unit]:
        """Headers that no translation unit included, parsed with the nearest TU's flags."""
        if not units:
            return []
        orphans: list[Unit] = []
        root = root.resolve()
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in HEADER_SUFFIXES:
                continue
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if rel in documented or is_ignored(rel):
                continue
            donor = _nearest_unit(rel, units)
            args = (*_without_language(donor.args), "-x", "c++")
            orphans.append(
                Unit(
                    language="cpp",
                    rel=rel,
                    source=str(path.resolve()),
                    args=args,
                    directory=donor.directory,
                )
            )
        return orphans

    def document_unit(self, unit: Unit, root: Path, is_ignored) -> list[FileDoc]:
        configure_libclang()
        return _parse(unit, root.resolve(), is_ignored)


def document_cpp_unit(payload: dict) -> dict:
    """Process-pool entry. Returns plain dicts so the parent does not share libclang state."""
    from markdown_serve.project_config import make_ignore

    try:
        if payload.get("libclang"):
            os.environ["LIBCLANG_PATH"] = payload["libclang"]
        configure_libclang(payload.get("libclang"))
        unit = Unit(
            language="cpp",
            rel=payload["rel"],
            source=payload["source"],
            args=tuple(payload["args"]),
            directory=payload.get("directory") or "",
        )
        root = Path(payload["root"])
        ignored = make_ignore(
            payload.get("ignore") or [],
            cache_dir=payload.get("cache_dir") or "",
            skip_dirs=payload.get("skip_dirs") or [],
        )
        docs = _parse(unit, root, ignored)
        return {"key": payload["key"], "rel": unit.rel, "docs": [_file_dict(doc) for doc in docs], "error": None}
    except Exception as exc:  # one bad TU should not kill the build
        return {"key": payload.get("key"), "rel": payload.get("rel", ""), "docs": [], "error": f"{payload.get('rel', '?')}: {exc}"}


def _without_language(args: tuple[str, ...]) -> tuple[str, ...]:
    kept: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == "-x":
            skip = True
            continue
        if arg.startswith("-x"):
            continue
        kept.append(arg)
    return tuple(kept)


def _nearest_unit(header_rel: str, units: list[Unit]) -> Unit:
    header_dir = str(Path(header_rel).parent.as_posix())
    best: Unit | None = None
    best_score = -1
    for unit in units:
        unit_dir = str(Path(unit.rel).parent.as_posix())
        score = _shared_prefix(header_dir, unit_dir)
        if score > best_score:
            best = unit
            best_score = score
    assert best is not None
    return best


def _shared_prefix(left: str, right: str) -> int:
    left_parts = [part for part in left.split("/") if part and part != "."]
    right_parts = [part for part in right.split("/") if part and part != "."]
    score = 0
    for a, b in zip(left_parts, right_parts):
        if a != b:
            break
        score += 1
    return score


@dataclass
class _Bucket:
    symbols: list[Symbol] = field(default_factory=list)
    by_usr: dict[str, Symbol] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)


def _parse(unit: Unit, root: Path, is_ignored) -> list[FileDoc]:
    from clang.cindex import CursorKind, Index, TranslationUnit

    index = Index.create()
    options = (
        TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
        | TranslationUnit.PARSE_INCOMPLETE
        | TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
    )
    tu = index.parse(unit.source, args=list(unit.args), options=options)
    if tu is None:
        raise RuntimeError("libclang returned no translation unit")
    buckets: dict[str, _Bucket] = {}
    lines: dict[str, list[str]] = {}
    kinds = _kinds(CursorKind)
    _visit(tu.cursor, None, root, is_ignored, buckets, lines, kinds)
    _collect_macros(tu, root, is_ignored, buckets, lines, kinds)
    docs: list[FileDoc] = []
    for rel, bucket in buckets.items():
        path = root / rel
        docs.append(
            FileDoc(
                rel_path=rel,
                language="cpp",
                file_doc=_file_comment(path),
                symbols=bucket.symbols,
                includes=bucket.includes,
            )
        )
    return docs


def _kinds(cursor_kind) -> dict[str, set]:
    def kinds(*names: str) -> set:
        found = set()
        for name in names:
            kind = getattr(cursor_kind, name, None)
            if kind is not None:
                found.add(kind)
        return found

    containers = kinds(
        "NAMESPACE",
        "CLASS_DECL",
        "STRUCT_DECL",
        "UNION_DECL",
        "CLASS_TEMPLATE",
        "ENUM_DECL",
    )
    interesting = containers | kinds(
        "FUNCTION_DECL",
        "CXX_METHOD",
        "CONSTRUCTOR",
        "DESTRUCTOR",
        "FUNCTION_TEMPLATE",
        "CONVERSION_FUNCTION",
        "FIELD_DECL",
        "VAR_DECL",
        "ENUM_CONSTANT_DECL",
        "TYPEDEF_DECL",
        "TYPE_ALIAS_DECL",
        "TYPE_ALIAS_TEMPLATE_DECL",
        "USING_DECLARATION",
        "MACRO_DEFINITION",
    )
    passthrough = kinds("LINKAGE_SPEC", "UNEXPOSED_DECL", "FRIEND_DECL")
    return {"containers": containers, "interesting": interesting, "passthrough": passthrough}


def _safe_kind(cursor):
    """Cursor kind, or None when libclang is newer than the Python bindings."""
    try:
        return cursor.kind
    except ValueError:
        return None


def _visit(cursor, parent_file: str | None, root, is_ignored, buckets, lines, kinds) -> None:
    from clang.cindex import AccessSpecifier, CursorKind

    for child in cursor.get_children():
        kind = _safe_kind(child)
        if kind is None:
            # Newer cursor kinds still wrap declarations we can document.
            _visit(child, parent_file, root, is_ignored, buckets, lines, kinds)
            continue
        if kind in kinds["passthrough"]:
            _visit(child, parent_file, root, is_ignored, buckets, lines, kinds)
            continue
        if kind == CursorKind.INCLUSION_DIRECTIVE:
            _add_include(child, root, is_ignored, buckets)
            continue
        rel = _rel_of(child, root)
        if rel is None or is_ignored(rel) or kind not in kinds["interesting"]:
            continue
        if kind == CursorKind.NAMESPACE and not child.spelling:
            # `namespace { }` has no name. Document its members in the enclosing scope.
            _visit(child, parent_file, root, is_ignored, buckets, lines, kinds)
            continue
        if not _visible(child, AccessSpecifier):
            continue
        bucket = buckets.setdefault(rel, _Bucket())
        usr = _usr(child)
        existing = bucket.by_usr.get(usr)
        if existing is None:
            symbol = _symbol(child, rel, lines)
            bucket.by_usr[usr] = symbol
            if parent_file == rel and _safe_kind(cursor) in kinds["containers"]:
                parent = _parent_symbol(cursor, buckets.get(rel))
                if parent is not None and parent is not symbol:
                    parent.children.append(symbol)
                else:
                    bucket.symbols.append(symbol)
            else:
                bucket.symbols.append(symbol)
            existing = symbol
        if kind in kinds["containers"]:
            _visit(child, rel, root, is_ignored, buckets, lines, kinds)


def _parent_symbol(cursor, bucket: _Bucket | None) -> Symbol | None:
    if bucket is None:
        return None
    return bucket.by_usr.get(_usr(cursor))


def _collect_macros(tu, root, is_ignored, buckets, lines, kinds) -> None:
    from clang.cindex import CursorKind

    if CursorKind.MACRO_DEFINITION not in kinds["interesting"]:
        return
    for cursor in tu.cursor.walk_preorder():
        if _safe_kind(cursor) != CursorKind.MACRO_DEFINITION:
            continue
        rel = _rel_of(cursor, root)
        if rel is None or is_ignored(rel):
            continue
        bucket = buckets.setdefault(rel, _Bucket())
        usr = _usr(cursor)
        if usr in bucket.by_usr:
            continue
        symbol = _symbol(cursor, rel, lines)
        bucket.by_usr[usr] = symbol
        bucket.symbols.append(symbol)


def _add_include(cursor, root, is_ignored, buckets) -> None:
    owner = _rel_of(cursor, root)
    if owner is None or is_ignored(owner):
        return
    included = cursor.get_included_file()
    if included is None:
        return
    rel = _path_rel(included.name, root)
    if rel is None or is_ignored(rel):
        return
    bucket = buckets.setdefault(owner, _Bucket())
    if rel not in bucket.includes:
        bucket.includes.append(rel)


def _visible(cursor, access) -> bool:
    spec = cursor.access_specifier
    return spec != access.PRIVATE


def _rel_of(cursor, root: Path) -> str | None:
    location = cursor.location
    if location.file is None:
        return None
    return _path_rel(location.file.name, root)


def _path_rel(path: str, root: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _usr(cursor) -> str:
    usr = cursor.get_usr() or ""
    if usr:
        return usr
    location = cursor.location
    line = location.line if location is not None else 0
    kind = _safe_kind(cursor)
    kind_name = kind.name if kind is not None else "unknown"
    return f"{kind_name}:{cursor.spelling}:{line}"


def _symbol(cursor, rel: str, lines: dict[str, list[str]]) -> Symbol:
    doc = _comment(cursor, lines)
    brief = ""
    if doc:
        normalized = doxygen_to_markdown(doc)
        for line in normalized.splitlines():
            if line.strip():
                brief = line.strip()
                break
    start = cursor.extent.start.line or cursor.location.line or 0
    end = cursor.extent.end.line or start
    access = cursor.access_specifier.name.lower()
    if access in {"invalid", "none"}:
        access = ""
    kind = _kind_name(cursor)
    if kind == "macro" and _is_include_guard(cursor, lines, start):
        kind = "include_guard"
    return Symbol(
        kind=kind,
        name=cursor.spelling or cursor.displayname,
        qualified_name=_qualified(cursor),
        signature=_signature(cursor),
        doc=doc,
        brief=brief,
        file=rel,
        line=start,
        end_line=end,
        access=access,
        usr=_usr(cursor),
    )


def _is_include_guard(cursor, lines: dict[str, list[str]], define_line: int) -> bool:
    """``#define NAME`` directly after ``#ifndef NAME`` (or ``#if !defined(NAME)``)."""
    location = cursor.location
    if location.file is None or define_line < 2:
        return False
    source = _source_lines(location.file.name, lines)
    index = define_line - 2
    while index >= 0 and not source[index].strip():
        index -= 1
    if index < 0:
        return False
    name = re.escape(cursor.spelling)
    guard = re.compile(rf"^\s*#\s*(?:ifndef\s+{name}|if\s+!\s*defined\s*\(?\s*{name}\s*\)?)\s*(?://.*|/\*.*)?$")
    return guard.match(source[index]) is not None


def _source_lines(path: str, lines: dict[str, list[str]]) -> list[str]:
    if path not in lines:
        try:
            lines[path] = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines[path] = []
    return lines[path]


def _type_spelling(clang_type) -> str:
    try:
        return clang_type.spelling
    except ValueError:
        return ""


def _kind_name(cursor) -> str:
    from clang.cindex import CursorKind

    kind = _safe_kind(cursor)
    mapping = {
        CursorKind.NAMESPACE: "namespace",
        CursorKind.STRUCT_DECL: "struct",
        CursorKind.UNION_DECL: "union",
        CursorKind.ENUM_DECL: "enum",
        CursorKind.ENUM_CONSTANT_DECL: "enum_constant",
        CursorKind.FUNCTION_DECL: "function",
        CursorKind.CXX_METHOD: "method",
        CursorKind.CONSTRUCTOR: "constructor",
        CursorKind.DESTRUCTOR: "destructor",
        CursorKind.FIELD_DECL: "field",
        CursorKind.VAR_DECL: "variable",
        CursorKind.TYPEDEF_DECL: "typedef",
        CursorKind.MACRO_DEFINITION: "macro",
    }
    for name, label in (
        ("CLASS_TEMPLATE", "class"),
        ("FUNCTION_TEMPLATE", "function"),
        ("TYPE_ALIAS_DECL", "using"),
        ("TYPE_ALIAS_TEMPLATE_DECL", "using"),
        ("USING_DECLARATION", "using"),
        ("CONVERSION_FUNCTION", "method"),
        ("CLASS_DECL", "class"),
    ):
        kind_const = getattr(CursorKind, name, None)
        if kind_const is not None and kind == kind_const:
            return label
    if kind is None:
        return "unknown"
    return mapping.get(kind, kind.name.lower())


def _qualified(cursor) -> str:
    from clang.cindex import CursorKind

    parts: list[str] = []
    current = cursor
    while current is not None and _safe_kind(current) != CursorKind.TRANSLATION_UNIT:
        if current.spelling and _safe_kind(current) != CursorKind.LINKAGE_SPEC:
            parts.append(current.spelling)
        current = current.semantic_parent
    return "::".join(reversed(parts))


def _signature(cursor) -> str:
    from clang.cindex import CursorKind

    kind = _safe_kind(cursor)
    if kind in {
        CursorKind.FUNCTION_DECL,
        CursorKind.CXX_METHOD,
        getattr(CursorKind, "FUNCTION_TEMPLATE", None),
        getattr(CursorKind, "CONVERSION_FUNCTION", None),
    }:
        result = _type_spelling(cursor.result_type)
        name = cursor.displayname or cursor.spelling
        return f"{result} {name}".strip()
    if kind in {CursorKind.CONSTRUCTOR, CursorKind.DESTRUCTOR}:
        return cursor.displayname or cursor.spelling
    if kind in {CursorKind.FIELD_DECL, CursorKind.VAR_DECL, CursorKind.ENUM_CONSTANT_DECL}:
        type_name = _type_spelling(cursor.type)
        return f"{type_name} {cursor.spelling}".strip()
    if kind == CursorKind.ENUM_DECL:
        return f"enum {cursor.spelling}".strip()
    if kind == CursorKind.TYPEDEF_DECL:
        try:
            underlying = cursor.underlying_typedef_type.spelling
        except Exception:
            underlying = ""
        return f"typedef {underlying} {cursor.spelling}".strip()
    return cursor.displayname or cursor.spelling


def _comment(cursor, lines: dict[str, list[str]]) -> str:
    raw = cursor.raw_comment or ""
    if raw.strip():
        return strip_comment_markers(raw)
    location = cursor.extent.start
    if location.file is None or not location.line:
        return ""
    return _preceding_comment(_source_lines(location.file.name, lines), location.line)


def _preceding_comment(source: list[str], start_line: int) -> str:
    index = start_line - 2
    if index < 0 or index >= len(source):
        return ""
    if not source[index].strip():
        return ""
    stripped = source[index].strip()
    if stripped.endswith("*/"):
        block = []
        while index >= 0:
            block.append(source[index])
            if "/*" in source[index]:
                break
            index -= 1
        return strip_comment_markers("\n".join(reversed(block)))
    if stripped.startswith("//"):
        block = []
        while index >= 0 and source[index].strip().startswith("//"):
            block.append(source[index])
            index -= 1
        return strip_comment_markers("\n".join(reversed(block)))
    return ""


def _file_comment(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    stripped = text.lstrip()
    if stripped.startswith("/*"):
        end = stripped.find("*/")
        if end < 0:
            return ""
        body = stripped[: end + 2]
        rest = stripped[end + 2 :]
        if "@file" in body or "\\file" in body or rest.startswith("\n\n"):
            return strip_comment_markers(body)
        return ""
    if stripped.startswith("//"):
        block = []
        for line in text.splitlines():
            if not line.strip():
                if block:
                    break
                continue
            if line.strip().startswith("//"):
                block.append(line)
            else:
                break
        body = "\n".join(block)
        if "@file" in body or "\\file" in body:
            return strip_comment_markers(body)
    return ""


def _file_dict(doc: FileDoc) -> dict:
    from dataclasses import asdict

    return asdict(doc)
