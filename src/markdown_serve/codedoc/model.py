"""Language-neutral documentation model. Backends fill it; markdown rendering reads it."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Symbol:
    kind: str
    name: str
    qualified_name: str
    signature: str
    doc: str
    brief: str
    file: str
    line: int
    end_line: int
    access: str
    usr: str
    children: list[Symbol] = field(default_factory=list)


@dataclass
class FileDoc:
    rel_path: str
    language: str
    file_doc: str
    symbols: list[Symbol] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Unit:
    """One parseable input. ``args`` are compiler flags with the compiler and output removed."""

    language: str
    rel: str
    source: str
    args: tuple[str, ...] = ()
    directory: str = ""


def count_symbols(symbols: list[Symbol]) -> int:
    return sum(1 + count_symbols(symbol.children) for symbol in symbols)


def merge_symbols(left: list[Symbol], right: list[Symbol]) -> list[Symbol]:
    """Union by USR. The entry with the longer doc comment wins; children merge."""
    order: list[str] = []
    by: dict[str, Symbol] = {}
    for symbol in left:
        by[symbol.usr] = symbol
        order.append(symbol.usr)
    for symbol in right:
        current = by.get(symbol.usr)
        if current is None:
            by[symbol.usr] = symbol
            order.append(symbol.usr)
            continue
        by[symbol.usr] = _richer(current, symbol)
    return [by[usr] for usr in order]


def _richer(left: Symbol, right: Symbol) -> Symbol:
    keep = left if len(left.doc) >= len(right.doc) else right
    other = right if keep is left else left
    return Symbol(
        kind=keep.kind,
        name=keep.name,
        qualified_name=keep.qualified_name or other.qualified_name,
        signature=keep.signature or other.signature,
        doc=keep.doc,
        brief=keep.brief or other.brief,
        file=keep.file,
        line=keep.line,
        end_line=keep.end_line or other.end_line,
        access=keep.access or other.access,
        usr=keep.usr,
        children=merge_symbols(left.children, right.children),
    )


def merge_file_docs(docs: list[FileDoc]) -> FileDoc | None:
    if not docs:
        return None
    base = docs[0]
    symbols = list(base.symbols)
    includes: list[str] = list(base.includes)
    file_doc = base.file_doc
    for doc in docs[1:]:
        symbols = merge_symbols(symbols, doc.symbols)
        for include in doc.includes:
            if include not in includes:
                includes.append(include)
        if len(doc.file_doc) > len(file_doc):
            file_doc = doc.file_doc
    return FileDoc(
        rel_path=base.rel_path,
        language=base.language,
        file_doc=file_doc,
        symbols=symbols,
        includes=includes,
    )
