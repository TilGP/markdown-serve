"""CLI entry point for markdown-serve."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
from pathlib import Path

import uvicorn

from markdown_serve.app import create_app


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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="markdown-serve",
        description="Live-preview markdown files in the current directory.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1)",
    )
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
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the browser automatically",
    )
    args = parser.parse_args()

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
        import threading
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    _set_tmux_window_title(f"markdown-serve: {root.name}")
    try:
        uvicorn.run(app, host=args.host, port=port, log_level="warning")
    finally:
        _reset_tmux_window_title()


if __name__ == "__main__":
    main()
