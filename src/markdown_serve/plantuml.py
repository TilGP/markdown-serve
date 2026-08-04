"""Local PlantUML rendering via Java (no remote server)."""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent / "assets" / "vendor"
VENDORED_JAR = VENDOR_DIR / "plantuml.jar"


class PlantUMLError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _resolve_plantuml_cmd() -> list[str]:
    """Return argv prefix that reads diagram source from stdin and writes SVG to stdout."""
    on_path = shutil.which("plantuml")
    if on_path:
        return [on_path, "-tsvg", "-pipe"]

    java = shutil.which("java")
    if java and VENDORED_JAR.is_file():
        return [java, "-jar", str(VENDORED_JAR), "-tsvg", "-pipe"]

    raise PlantUMLError(
        "PlantUML is unavailable offline. Install a JRE and keep "
        f"{VENDORED_JAR.name} in assets/vendor/, or install a `plantuml` binary on PATH."
    )


def render_plantuml_svg(source: str) -> str:
    text = source.strip()
    if not text:
        raise PlantUMLError("Empty PlantUML source")
    if "@start" not in text.lower():
        text = f"@startuml\n{text}\n@enduml\n"

    cmd = _resolve_plantuml_cmd()
    try:
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PlantUMLError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise PlantUMLError("PlantUML timed out") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", errors="replace").strip()
        raise PlantUMLError(detail or f"PlantUML exited with code {proc.returncode}")

    svg = proc.stdout.decode("utf-8", errors="replace").strip()
    if "<svg" not in svg.lower():
        detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise PlantUMLError(detail or "PlantUML did not return SVG")
    return svg
