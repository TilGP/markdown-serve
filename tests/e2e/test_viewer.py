from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e.conftest import WORKSPACE
from tests.e2e.helpers import open_readme, wait_for_preview


def test_loads_markdown_sidebar_and_diagrams(page: Page) -> None:
    open_readme(page)
    expect(page.locator("#nav a.nav-link.active").filter(has_text="README.md")).to_be_visible()
    page.locator("#nav summary").filter(has_text="docs").click()
    expect(page.locator("#nav a.nav-link", has_text="install.md")).to_be_visible()
    expect(page.locator("#content .diagram-mermaid svg")).to_be_visible()
    expect(page.locator("#toc a", has_text="Diagrams")).to_be_visible()


def test_theme_toggle_switches_data_theme(page: Page) -> None:
    open_readme(page)
    html = page.locator("html")
    expect(html).to_have_attribute("data-theme", "light")
    page.locator("#theme-toggle").click()
    expect(html).to_have_attribute("data-theme", "dark")
    wait_for_preview(page)
    expect(page.locator("#content .diagram-mermaid svg")).to_be_visible()


def test_file_finder_filters_sidebar(page: Page) -> None:
    open_readme(page)
    page.locator("#finder").fill("install")
    expect(page.locator("#nav a.nav-link")).to_have_count(1)
    expect(page.locator("#nav a.nav-link")).to_contain_text("install.md")


def test_expanded_folders_survive_a_file_change(page: Page) -> None:
    open_readme(page)
    docs = page.locator("#nav details").filter(has=page.locator("summary", has_text="docs"))
    docs.locator("summary").click()
    expect(docs).to_have_attribute("open", "")

    created = WORKSPACE / "scratch.md"
    try:
        created.write_text("# Scratch\n", encoding="utf-8")
        expect(page.locator("#nav a.nav-link", has_text="scratch.md")).to_be_visible()
        expect(docs).to_have_attribute("open", "")
    finally:
        Path(created).unlink(missing_ok=True)

    expect(page.locator("#nav a.nav-link", has_text="scratch.md")).to_have_count(0)
    expect(docs).to_have_attribute("open", "")


def test_content_search_finds_snippet(page: Page) -> None:
    open_readme(page)
    page.locator("#search-mode-content").click()
    page.locator("#finder").fill("'locally via Java")
    expect(page.locator("#nav .content-results a.nav-link")).to_contain_text("README.md")
    expect(page.locator("#nav .search-snippet")).to_contain_text("locally via Java")
