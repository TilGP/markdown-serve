"""Shared Playwright helpers for viewer e2e tests."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def wait_for_preview(page: Page) -> None:
    expect(page.locator("#status")).to_have_class("live", timeout=15_000)
    expect(page.locator("#content h1")).to_be_visible()
    page.wait_for_function(
        """() => {
          const mermaid = [...document.querySelectorAll(".diagram-mermaid")];
          const server = [...document.querySelectorAll(".diagram-plantuml, .diagram-excalidraw")];
          const mermaidReady = mermaid.every((node) => node.querySelector("svg"));
          const serverReady = server.every(
            (node) => node.querySelector("svg") || node.querySelector(".diagram-error")
          );
          return mermaidReady && serverReady && !document.querySelector(".diagram-skeleton");
        }""",
        timeout=30_000,
    )
    page.wait_for_function("() => document.fonts.status === 'loaded'")
    page.evaluate("() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); }")


def open_readme(page: Page) -> None:
    page.goto("/README.md")
    wait_for_preview(page)
