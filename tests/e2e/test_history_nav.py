from playwright.sync_api import Page, expect

from tests.e2e.helpers import open_readme, wait_for_preview


def test_browser_back_forward_navigate_between_files(page: Page) -> None:
    open_readme(page)
    page.locator("#nav summary").filter(has_text="docs").click()
    page.locator("#nav a.nav-link", has_text="install.md").click()
    wait_for_preview(page)
    expect(page.locator("#nav a.nav-link.active")).to_contain_text("install.md")
    assert page.url.endswith("/docs/install.md")

    page.go_back()
    wait_for_preview(page)
    expect(page.locator("#nav a.nav-link.active")).to_contain_text("README.md")
    assert page.url.endswith("/README.md")

    page.go_forward()
    wait_for_preview(page)
    expect(page.locator("#nav a.nav-link.active")).to_contain_text("install.md")
    assert page.url.endswith("/docs/install.md")


def test_browser_back_closes_enlarged_diagram(page: Page) -> None:
    open_readme(page)
    page.locator("#nav summary").filter(has_text="docs").click()
    page.locator("#nav a.nav-link", has_text="install.md").click()
    wait_for_preview(page)

    page.locator("#nav a.nav-link", has_text="README.md").click()
    wait_for_preview(page)
    zoom_btn = page.locator(".zoomable:has(.diagram-mermaid) .zoom-btn")
    expect(zoom_btn).to_be_visible()
    zoom_btn.click()
    expect(page.locator(".lightbox")).to_be_visible()

    page.go_back()
    wait_for_preview(page)
    expect(page.locator("#nav a.nav-link.active")).to_contain_text("install.md")
    expect(page.locator(".lightbox")).to_be_hidden()
