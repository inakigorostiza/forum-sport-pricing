"""Headless-browser fetcher for hosts that refuse plain HTTP requests.

Deporvillage, Sprinter and i-Run return 403 to any non-browser client — their
robots.txt is not even readable. Fetching them therefore means presenting as a
real browser, which is a commercial/ToS decision the client has taken; it is not
something this module should make easy to do casually. Hence:

  * those competitors stay `enabled = false` until switched on deliberately;
  * the delay defaults higher (6s) than for permissive sites;
  * only public product pages are fetched — never a login, cart or account page;
  * every request still goes through the crawl_log.

Requires Playwright:  pip install playwright && playwright install chromium
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .fetch import FetchStats, UA_BROWSER


@dataclass
class HeadlessFetcher:
    delay: float = 6.0
    ua: str = UA_BROWSER
    stats: FetchStats = field(default_factory=FetchStats)
    _last: float | None = None
    _browser = None
    _pw = None

    def _start(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run:\n"
                "  pip install playwright && playwright install chromium"
            ) from None
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)

    def _wait(self) -> None:
        if self._last is not None:
            gap = time.monotonic() - self._last
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self.stats.gaps.append(round(time.monotonic() - self._last, 2))
        self._last = time.monotonic()

    def get(self, url: str, *, timeout: int = 45) -> str | None:
        self._start()
        self._wait()
        ctx = self._browser.new_context(user_agent=self.ua, locale="es-ES")
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            # Structured data is usually server-rendered; a short settle is enough.
            page.wait_for_timeout(1200)
            html = page.content()
            self.stats.pages += 1
            return html
        except Exception as e:
            self.stats.errors += 1
            self.stats.last_error = f"{type(e).__name__}: {e}"
            return None
        finally:
            ctx.close()

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
