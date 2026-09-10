"""Browser fixtures: isolated config, demo workspace, live uvicorn server."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from markdown_serve import config as config_mod
from markdown_serve.app import create_app
from markdown_serve.config import DEFAULT_CONFIG

WORKSPACE = Path(__file__).resolve().parent / "workspace"
SCREENSHOT_VIEWPORT = {"width": 1182, "height": 935}


@pytest.fixture(scope="session")
def isolated_config_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("viewer-config") / "config.json"
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def live_server_url(isolated_config_path: Path) -> Iterator[str]:
    previous = config_mod.CONFIG_PATH
    config_mod.CONFIG_PATH = isolated_config_path
    app = create_app(WORKSPACE)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("markdown-serve failed to start for e2e tests")

    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        config_mod.CONFIG_PATH = previous


@pytest.fixture(scope="session")
def base_url(live_server_url: str) -> str:
    return live_server_url


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    return {
        **browser_context_args,
        "viewport": SCREENSHOT_VIEWPORT,
        "device_scale_factor": 2,
        "color_scheme": "light",
    }


@pytest.fixture(autouse=True)
def reset_viewer_config(isolated_config_path: Path) -> Iterator[None]:
    isolated_config_path.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8"
    )
    yield
