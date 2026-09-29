"""Build the code-doc cache. Parsing runs in a process pool; jobs=1 stays in-process."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from markdown_serve.codedoc.cache import (
    cache_dir,
    empty_language,
    index_rel,
    load_manifest,
    page_path,
    save_manifest,
    select_stale_units,
    sha256_file,
    unit_fingerprint,
    unit_key,
)
from markdown_serve.codedoc.cpp.backend import document_cpp_unit, find_libclang
from markdown_serve.codedoc.python.backend import document_python_unit
from markdown_serve.codedoc.markdown import render_file_markdown, render_index_markdown
from markdown_serve.codedoc.model import FileDoc, Symbol, count_symbols, merge_file_docs
from markdown_serve.codedoc.registry import active_languages, backend_for
from markdown_serve.project_config import load_project_config, make_ignore


@dataclass
class Progress:
    phase: str
    done: int
    total: int
    current: str
    errors: list[str] = field(default_factory=list)
    language: str = ""


def resolve_jobs(cfg: dict, override: int | None) -> int:
    if override is not None and override > 0:
        return override
    configured = cfg["codedoc"].get("jobs")
    if isinstance(configured, int) and configured > 0:
        return configured
    return max(1, os.cpu_count() or 1)


def build(
    root: Path,
    languages: list[str] | None = None,
    progress: Callable[[Progress], None] | None = None,
    cancel: object | None = None,
    force: bool = False,
    jobs: int | None = None,
    clean: bool = False,
) -> dict:
    """Rebuild the cache. ``cancel`` is a ``threading.Event`` (or anything with ``is_set``)."""
    root = root.resolve()
    cfg = load_project_config(root)
    selected = languages if languages is not None else active_languages(root, cfg)
    cache = cache_dir(root, cfg)
    if clean and cache.exists():
        shutil.rmtree(cache)
    cache.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(cache)
    from markdown_serve.app import SKIP_DIRS

    ignored = make_ignore(
        cfg["ignore"],
        cache_dir=cfg["codedoc"]["cache_dir"],
        skip_dirs=SKIP_DIRS,
    )
    worker_jobs = resolve_jobs(cfg, jobs)
    errors: list[str] = []
    file_count = 0
    symbol_count = 0

    def report(phase: str, done: int, total: int, current: str, language: str) -> None:
        if progress is not None:
            progress(Progress(phase, done, total, current, list(errors), language))

    for language in selected:
        if _cancelled(cancel):
            errors.append("cancelled")
            break
        try:
            backend = backend_for(language)
        except KeyError as exc:
            errors.append(str(exc))
            continue
        status = backend.check(root, cfg)
        if not status.available:
            errors.extend(status.missing)
            report("check", 0, 0, "", language)
            continue
        report("discover", 0, 0, "", language)
        try:
            units = backend.discover(root, cfg, ignored)
        except (OSError, ValueError) as exc:
            errors.append(f"{language}: {exc}")
            continue
        lang_manifest = manifest.setdefault("languages", {}).setdefault(language, empty_language())
        if force:
            lang_manifest = empty_language()
            manifest["languages"][language] = lang_manifest
        _, produced = _parse_units(
            root, cfg, language, units, lang_manifest, worker_jobs, force, cancel, errors, report, SKIP_DIRS
        )
        documented = set(produced)
        extras = backend.extra_units(root, cfg, ignored, units, documented)
        if extras and not _cancelled(cancel):
            _, extra_produced = _parse_units(
                root, cfg, language, extras, lang_manifest, worker_jobs, force, cancel, errors, report, SKIP_DIRS
            )
            produced.update(extra_produced)
        if not _cancelled(cancel):
            seen_keys = {unit_key(unit.rel, unit.args) for unit in (*units, *extras)}
            for key in list(lang_manifest.get("units") or {}):
                if key not in seen_keys:
                    lang_manifest["units"].pop(key, None)
            _drop_stale(cache, language, lang_manifest, root)
            _drop_unlisted(cache, language, lang_manifest)
            files = sorted(lang_manifest.get("files") or {})
            index = index_rel(cfg, language)
            text = render_index_markdown(language, files, index)
            index_path = root / index
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(text, encoding="utf-8")
            tools = {check.name: check.hint for check in status.checks}
            lang_manifest["tools"] = tools
        file_count += len(lang_manifest.get("files") or {})
        symbol_count += sum(int((info or {}).get("symbols") or 0) for info in (lang_manifest.get("files") or {}).values())
        report("done", file_count, file_count, "", language)

    save_manifest(cache, manifest)
    report("done", file_count, file_count, "", selected[-1] if selected else "")
    return {
        "files": file_count,
        "symbols": symbol_count,
        "errors": errors,
        "cache": str(cache),
        "cancelled": _cancelled(cancel),
    }


def _parse_units(root, cfg, language, units, lang_manifest, jobs, force, cancel, errors, report, skip_dirs):
    rows = []
    file_sha: dict[str, str] = {}
    for unit in units:
        source = Path(unit.source)
        try:
            fingerprint = unit_fingerprint(source, unit.args)
        except OSError as exc:
            errors.append(f"{unit.rel}: {exc}")
            continue
        key = unit_key(unit.rel, unit.args)
        rows.append((key, unit, fingerprint))
        if unit.rel not in file_sha:
            try:
                file_sha[unit.rel] = sha256_file(source)
            except OSError:
                pass
    # Hashes for previously produced headers, so a header edit invalidates the TU.
    for stored in (lang_manifest.get("units") or {}).values():
        for rel in stored.get("files") or []:
            if rel in file_sha:
                continue
            path = root / rel
            if path.is_file():
                try:
                    file_sha[rel] = sha256_file(path)
                except OSError:
                    pass
    selectable = [(key, unit.rel, fingerprint) for key, unit, fingerprint in rows]
    stale_idx, skipped_idx = select_stale_units(selectable, lang_manifest, file_sha, force=force)
    produced: dict[str, list[str]] = {}
    for index in skipped_idx:
        key, unit, _fingerprint = rows[index]
        produced[key] = list((lang_manifest.get("units") or {}).get(key, {}).get("files") or [])

    written: dict[str, FileDoc] = {}
    stale_rows = [rows[index] for index in stale_idx]
    total = len(stale_rows)
    if not stale_rows:
        return written, set().union(*produced.values()) if produced else set()

    libclang = find_libclang(cfg["codedoc"].get(language, {}).get("libclang") if language == "cpp" else None)
    payloads = [
        {
            "key": key,
            "rel": unit.rel,
            "source": unit.source,
            "args": list(unit.args),
            "directory": unit.directory,
            "root": str(root),
            "ignore": list(cfg["ignore"]),
            "cache_dir": cfg["codedoc"]["cache_dir"],
            "skip_dirs": sorted(skip_dirs),
            "libclang": libclang,
        }
        for key, unit, _fingerprint in stale_rows
    ]
    results = _run_payloads(language, payloads, jobs, cancel, errors, report, total)
    grouped: dict[str, list[FileDoc]] = {}
    by_key_files: dict[str, list[str]] = {}
    failed: set[str] = set()
    for result in results:
        if result.get("error"):
            errors.append(result["error"])
            # Leave the unit out of the manifest so the next build retries it.
            failed.add(result.get("key") or "")
            continue
        docs = [_file_from_dict(item) for item in result.get("docs") or []]
        files = sorted({doc.rel_path for doc in docs})
        by_key_files[result.get("key") or ""] = files
        for doc in docs:
            grouped.setdefault(doc.rel_path, []).append(doc)
    for rel, docs in grouped.items():
        merged = merge_file_docs(docs)
        if merged is not None:
            written[rel] = merged

    cache = cache_dir(root, cfg)
    for rel, doc in written.items():
        path = page_path(cache, language, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_file_markdown(doc, root), encoding="utf-8")
        source = root / rel
        lang_manifest.setdefault("files", {})[rel] = {
            "sha256": sha256_file(source) if source.is_file() else "",
            "symbols": count_symbols(doc.symbols),
        }
    for key, unit, fingerprint in stale_rows:
        if key in failed:
            continue
        files = by_key_files.get(key, [])
        lang_manifest.setdefault("units", {})[key] = {"hash": fingerprint, "files": files}
        produced[key] = files
    all_files: set[str] = set()
    for files in produced.values():
        all_files.update(files)
    return written, all_files


def _run_payloads(language, payloads, jobs, cancel, errors, report, total):
    results = []
    worker = {"cpp": document_cpp_unit, "python": document_python_unit}.get(language)
    if worker is None:
        errors.append(f"{language}: no worker")
        return results
    if jobs <= 1:
        for done, payload in enumerate(payloads, start=1):
            if _cancelled(cancel):
                errors.append("cancelled")
                break
            results.append(worker(payload))
            report("parse", done, total, payload["rel"], language)
        return results

    import multiprocessing

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=jobs, mp_context=context) as pool:
        futures = {pool.submit(worker, payload): payload for payload in payloads}
        done = 0
        for future in as_completed(futures):
            payload = futures[future]
            if _cancelled(cancel):
                pool.shutdown(wait=False, cancel_futures=True)
                errors.append("cancelled")
                break
            done += 1
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(f"{payload['rel']}: {exc}")
            report("parse", done, total, payload["rel"], language)
    return results


def _drop_unlisted(cache: Path, language: str, lang_manifest: dict) -> None:
    """Remove generated pages whose source is no longer in the manifest."""
    keep = set(lang_manifest.get("files") or {})
    lang_root = cache / language
    if not lang_root.is_dir():
        return
    for path in lang_root.rglob("*.md"):
        if path.name == "index.md":
            continue
        source_rel = path.relative_to(lang_root).as_posix()[: -len(".md")]
        if source_rel not in keep:
            path.unlink(missing_ok=True)


def _drop_stale(cache: Path, language: str, lang_manifest: dict, root: Path) -> None:
    files = lang_manifest.setdefault("files", {})
    for rel in list(files):
        if not (root / rel).is_file():
            page = page_path(cache, language, rel)
            page.unlink(missing_ok=True)
            files.pop(rel, None)


def _file_from_dict(data: dict) -> FileDoc:
    return FileDoc(
        rel_path=data["rel_path"],
        language=data["language"],
        file_doc=data.get("file_doc") or "",
        symbols=[_symbol_from_dict(item) for item in data.get("symbols") or []],
        includes=list(data.get("includes") or []),
    )


def _symbol_from_dict(data: dict) -> Symbol:
    return Symbol(
        kind=data.get("kind") or "",
        name=data.get("name") or "",
        qualified_name=data.get("qualified_name") or "",
        signature=data.get("signature") or "",
        doc=data.get("doc") or "",
        brief=data.get("brief") or "",
        file=data.get("file") or "",
        line=int(data.get("line") or 0),
        end_line=int(data.get("end_line") or 0),
        access=data.get("access") or "",
        usr=data.get("usr") or "",
        children=[_symbol_from_dict(item) for item in data.get("children") or []],
    )


def _cancelled(cancel: object | None) -> bool:
    if cancel is None:
        return False
    is_set = getattr(cancel, "is_set", None)
    return bool(is_set()) if callable(is_set) else False

