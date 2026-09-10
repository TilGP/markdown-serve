"""Capture light/dark screenshots and write readme_files/combined.png."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from playwright.sync_api import Page, expect

from tests.e2e.helpers import open_readme, wait_for_preview

REPO_ROOT = Path(__file__).resolve().parents[2]
COMBINED_PNG = REPO_ROOT / "readme_files" / "combined.png"


def _combine_diagonal(light: Image.Image, dark: Image.Image) -> Image.Image:
    light_rgba = light.convert("RGBA")
    dark_rgba = dark.convert("RGBA")
    if light_rgba.size != dark_rgba.size:
        dark_rgba = dark_rgba.resize(light_rgba.size, Image.Resampling.LANCZOS)
    width, height = light_rgba.size
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon([(0, 0), (0, height), (width, height)], fill=255)
    combined = dark_rgba.copy()
    combined.paste(light_rgba, mask=mask)
    return combined


@pytest.mark.screenshot
def test_generate_readme_combined_png(page: Page) -> None:
    open_readme(page)
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    light_png = page.screenshot(type="png", scale="device")

    page.locator("#theme-toggle").dispatch_event("click")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    wait_for_preview(page)
    dark_png = page.screenshot(type="png", scale="device")

    light = Image.open(BytesIO(light_png))
    dark = Image.open(BytesIO(dark_png))
    combined = _combine_diagonal(light, dark)
    COMBINED_PNG.parent.mkdir(parents=True, exist_ok=True)
    combined.save(COMBINED_PNG, format="PNG", optimize=True)

    assert COMBINED_PNG.is_file()
    with Image.open(COMBINED_PNG) as written:
        assert written.size[0] > 1000
        assert written.size[1] > 800
