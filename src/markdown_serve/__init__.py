"""CLI entry point for markdown-serve."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import uvicorn

from markdown_serve.app import create_app
from markdown_serve.codedoc.builder import Progress, build
from markdown_serve.codedoc.registry import BACKENDS, active_languages, check_language
from markdown_serve.project_config import load_project_config


def _set_tmux_window_title(title: str) -> None:
    """Rename the current tmux window, if running inside tmux.

    rename-window also turns off automatic-rename for the window, so tmux
    stops overwriting the name with the foreground command.
    """
    if not os.getenv("TMUX"):
        return
    subprocess.run(["tmux", "rename-window", title], check=False)


def _reset_tmux_window_title() -> None:
    """Hand the window name back to tmux's automatic renaming."""
    if not os.getenv("TMUX"):
        return
    subprocess.run(["tmux", "set-window-option", "automatic-rename", "on"], check=False)


def _find_free_port(host: str, preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host if host != "0.0.0.0" else "", preferred))
            return preferred
        except OSError:
            sock.bind((host if host != "0.0.0.0" else "", 0))
            return int(sock.getsockname()[1])


def _serve(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="markdown-serve serve",
        description="Live-preview markdown files in the current directory.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8765,
        help="Port to bind (default: 8765; falls back to a free port if taken)",
    )
    parser.add_argument(
        "--root",
        "-r",
        type=Path,
        default=None,
        help="Directory to serve (default: current working directory)",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args(argv)

    root = (args.root or Path.cwd()).resolve()
    if not root.is_dir():
        parser.error(f"Not a directory: {root}")

    port = _find_free_port(args.host, args.port)
    app = create_app(root)

    display_host = "localhost" if args.host in {"0.0.0.0", "127.0.0.1"} else args.host
    url = f"http://{display_host}:{port}/"
    print(f"Serving markdown from {root}", flush=True)
    print(f"Open {url}", flush=True)

    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser_open(url)).start()

    _set_tmux_window_title(f"markdown-serve: {root.name}")
    try:
        uvicorn.run(app, host=args.host, port=port, log_level="warning")
    finally:
        _reset_tmux_window_title()


def webbrowser_open(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def _print_progress(progress: Progress) -> None:
    if progress.phase == "parse" and progress.total:
        print(
            f"[{progress.language}] {progress.done}/{progress.total} {progress.current}",
            flush=True,
        )


def _build_cache(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="markdown-serve build-cache",
        description="Build the code-documentation cache (C++ via compile_commands.json, Python via the stdlib AST).",
    )
    parser.add_argument("--root", "-r", type=Path, default=None, help="Project root (default: cwd)")
    parser.add_argument(
        "--lang",
        action="append",
        default=None,
        help="Language to build (repeatable; default: codedoc.languages in .markdown-serve.json)",
    )
    parser.add_argument("-j", type=int, default=None, help="Parallel parse jobs (default: CPU count)")
    parser.add_argument("--force", action="store_true", help="Reparse every unit")
    parser.add_argument("--clean", action="store_true", help="Delete the cache directory first")
    parser.add_argument("--check", action="store_true", help="Print tool status and exit")
    args = parser.parse_args(argv)

    root = (args.root or Path.cwd()).resolve()
    if not root.is_dir():
        parser.error(f"Not a directory: {root}")
    cfg = load_project_config(root)
    languages = args.lang or active_languages(root, cfg)
    if args.check:
        failed = False
        for language in languages:
            if language not in BACKENDS:
                print(f"{language}: unknown language", flush=True)
                failed = True
                continue
            status = check_language(root, cfg, language)
            print(f"{language}: {'ready' if status.available else 'unavailable'}", flush=True)
            for check in status.checks:
                mark = "ok" if check.ok else "missing"
                print(f"  {mark:7} {check.name}: {check.hint}", flush=True)
            if not status.available:
                failed = True
        raise SystemExit(1 if failed else 0)

    result = build(
        root,
        languages=languages,
        progress=_print_progress,
        force=args.force,
        jobs=args.j,
        clean=args.clean,
    )
    print(
        f"Wrote {result['files']} files ({result['symbols']} symbols) to {result['cache']}",
        flush=True,
    )
    for error in result["errors"]:
        print(f"error: {error}", file=sys.stderr, flush=True)
    if result["errors"] and result["files"] == 0:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        if args and args[0] in {"-h", "--help"}:
            print(
                "usage: markdown-serve [serve] [options]\n"
                "       markdown-serve build-cache [options]\n"
                "\n"
                "Live-preview markdown. `serve` is the default when no subcommand is given.\n"
                "\n"
                "subcommands:\n"
                "  serve         preview the working directory (default)\n"
                "  build-cache   build the optional code-documentation cache\n",
                flush=True,
            )
            return
    if args and args[0] == "build-cache":
        _build_cache(args[1:])
        return
    if args and args[0] == "serve":
        args = args[1:]
    _serve(args)


if __name__ == "__main__":
    main()
