import os
import time
from typing import Optional

from rustwright.sync_api import Browser, BrowserContext, Page, Playwright
from core.controller import controller


def launch_browser(playwright: Playwright, headless: Optional[bool] = None) -> tuple[Browser, BrowserContext, Page]:
    """Launch Chromium browser and return (browser, context, page) tuple."""
    if headless is None:
        headless = os.environ.get("HEADLESS", "false").lower() in ("true", "1")

    mode_label = "headless" if headless else "non-headless"
    print(f"[*] Launching Chromium browser ({mode_label})...")

    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    page = context.new_page()
    return browser, context, page


def safe_wait_dom(page: Page, settle_ms: int = 1500) -> None:
    """Wait for DOM content to settle without hanging on infinite background network telemetry."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(settle_ms)


def wait_for_spa_ready(page: Page, timeout_sec: int = 15) -> None:
    """Wait for client-side Single Page Application (Workday / React) to render real content and title."""
    start_time = time.time()
    print("[*] Waiting for career portal to render (Workday SPA hydration)...")

    while time.time() - start_time < timeout_sec:
        title = page.title()
        if title and title.strip():
            break

        try:
            has_content = page.locator(
                "[data-automation-id='jobPostingHeader'], "
                "[data-automation-id='adventureButton'], "
                "main, article, h1, h2, form, input"
            ).count()
            if has_content > 0:
                break
        except Exception:
            pass

        page.wait_for_timeout(500)

    page.wait_for_timeout(1500)
    print(f"[+] Portal ready: '{page.title()}' ({page.url})")


def navigate_to_url(page: Page, url: str) -> bool:
    """Navigate to target URL using domcontentloaded and wait for SPA hydration."""
    print(f"\n[->] Navigating to: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        wait_for_spa_ready(page)
        return True
    except Exception as e:
        curr_url = page.url or ""
        if curr_url and curr_url != "about:blank":
            print(f"\033[1;33m[!] Telemetry slow, but DOM loaded: '{page.title()}'\033[0m")
            wait_for_spa_ready(page)
            return True

        print(f"\033[1;31m[X] Navigation timeout or error: {e}\033[0m")
        controller.is_paused = True
        controller.wait_if_paused(
            reason=f"Navigation timeout while loading portal ({e}).",
            details=[f"URL: {url}", "Portal took too long to respond or background requests blocked."],
            action="Check the Chromium window. Refresh if needed, then press [Enter] or [R]."
        )
        return False
