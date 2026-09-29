"""Load ``compile_commands.json`` into compiler-flag lists libclang can parse."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

from markdown_serve.codedoc.model import Unit

_DROP = {"-c", "-M", "-MM", "-MD", "-MMD", "-MG", "-MP", "-MV"}
_DROP_WITH_ARG = {"-o", "-MF", "-MT", "-MQ", "-MJ"}

_resource_dir_cache: dict[str, str | None] = {}


def compiler_and_args(argv: list[str], source: Path, directory: Path | None = None) -> tuple[str, list[str]]:
    """Drop the compiler, the input file, ``-c``, ``-o``, and dependency-file flags."""
    if not argv:
        return "", []
    compiler = argv[0]
    args: list[str] = []
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in _DROP_WITH_ARG:
            i += 2
            continue
        if arg in _DROP or (arg.startswith("-M") and not arg.startswith("-m")):
            i += 1
            continue
        if _is_source(arg, source, directory):
            i += 1
            continue
        args.append(arg)
        i += 1
    return compiler, args


def _is_source(arg: str, source: Path, directory: Path | None) -> bool:
    if arg.startswith("-"):
        return False
    candidate = Path(arg)
    if not candidate.is_absolute() and directory is not None:
        candidate = directory / candidate
    try:
        return candidate.resolve() == source
    except OSError:
        return False


def resource_dir(compiler: str) -> str | None:
    if compiler in _resource_dir_cache:
        return _resource_dir_cache[compiler]
    executable = compiler if Path(compiler).is_file() else shutil.which(compiler)
    if not executable:
        _resource_dir_cache[compiler] = None
        return None
    try:
        result = subprocess.run(
            [executable, "-print-resource-dir"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _resource_dir_cache[compiler] = None
        return None
    value = result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    _resource_dir_cache[compiler] = value
    return value


def with_resource_dir(compiler: str, args: list[str]) -> list[str]:
    if any(arg == "-resource-dir" or arg.startswith("-resource-dir=") for arg in args):
        return args
    path = resource_dir(compiler)
    if not path:
        return args
    return [*args, "-resource-dir", path]


def load_units(root: Path, compile_commands: Path, is_ignored) -> list[Unit]:
    raw = json.loads(compile_commands.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{compile_commands} is not a compile_commands list")
    root = root.resolve()
    units: list[Unit] = []
    for entry in raw:
        if not isinstance(entry, dict) or "file" not in entry:
            continue
        directory = Path(entry.get("directory") or ".")
        source = Path(entry["file"])
        if not source.is_absolute():
            source = directory / source
        try:
            source = source.resolve()
            rel = source.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if is_ignored(rel):
            continue
        if "arguments" in entry and isinstance(entry["arguments"], list):
            argv = [str(part) for part in entry["arguments"]]
        elif isinstance(entry.get("command"), str):
            argv = shlex.split(entry["command"])
        else:
            continue
        compiler, args = compiler_and_args(argv, source, directory)
        args = with_resource_dir(compiler, args)
        units.append(
            Unit(
                language="cpp",
                rel=rel,
                source=str(source),
                args=tuple(args),
                directory=str(directory),
            )
        )
    return units
