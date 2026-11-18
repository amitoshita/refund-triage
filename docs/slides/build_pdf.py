"""Render docs/slides/slides.html to docs/slides.pdf (one 1280x720 page per slide).

Needs Playwright with Chromium: pip install playwright && playwright install chromium
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto((HERE / "slides.html").as_uri())
    page.wait_for_load_state("networkidle")
    page.pdf(path=str(HERE.parent / "slides.pdf"), width="1280px", height="720px", print_background=True)
    for i, el in enumerate(page.locator("section.slide").all(), 1):  # PNG previews for review
        page.emulate_media(media="print")
        el.screenshot(path=str(HERE / f"slide_{i}.png"))
    browser.close()
