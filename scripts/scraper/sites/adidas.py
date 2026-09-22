"""adidas.es — targeted scraper.

adidas differs from the sitemap_jsonld sites in three ways, and each one shapes
this module:

1. **Akamai Bot Manager blocks ordinary automation.** Plain HTTP, real Chrome,
   and Chrome with the puppeteer stealth plugin all receive 403 on product
   pages — including on URLs taken from adidas's own sitemap. Patchright (a
   patched Playwright launched as a persistent context, with no automation
   flags) does get through. Their robots.txt actually *allows* product pages
   (`Allow: /*/*.html*`); it is the WAF, not the stated policy, that refuses.

2. **They publish no GTIN.** The JSON-LD ProductGroup carries sizes, prices and
   availability but no gtin13, so the EAN join used elsewhere cannot work.
   Matching is on the article code instead — the last path segment of the
   product URL (/zapatilla-galaxy-6/GW4139.html), which is exactly what our
   catalogue stores as models.ref_prov.

3. **We do not need their catalogue, only ours.** Their sitemap has 15.337
   products; 66 of them carry an article code we stock. Discovery intersects
   the two, so the crawl is ~66 pages rather than thousands.

robots.txt disallows /api/products/*/availability and /api/search/product/* —
neither is touched here. Only public product pages are fetched.
"""

from __future__ import annotations

import pathlib
import re
import time

SITEMAP = "https://www.adidas.es/glass/sitemaps/adidas/ES/es/sitemaps/adidas-ES-es-es-product.xml"
CODE_RE = re.compile(r"/([A-Z0-9]{5,7})\.html$")
PROFILE = "/tmp/patchright_adidas"


class AdidasFetcher:
    """Patchright persistent context. Opened once, reused for the whole run:
    re-launching per page would be both slower and more conspicuous."""

    def __init__(self, delay_s: float = 10.0):
        self.delay = float(delay_s)
        self._last: float | None = None
        self._ctx = None
        self._pw = None
        self._page = None
        self.pages = 0
        self.errors = 0
        self.gaps: list[float] = []

    def _start(self):
        if self._ctx is not None:
            return
        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "adidas needs patchright (ordinary Playwright is detected):\n"
                "  pip install patchright && python3 -m patchright install chromium"
            ) from None
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE, channel="chromium",
            headless=False, no_viewport=True, locale="es-ES")
        self._page = self._ctx.new_page()

    def _wait(self):
        if self._last is not None:
            gap = time.monotonic() - self._last
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self.gaps.append(round(time.monotonic() - self._last, 2))
        self._last = time.monotonic()

    def get(self, url: str, *, settle_ms: int = 2000, timeout: int = 90) -> str | None:
        """`timeout` is SECONDS, matching PoliteFetcher. Playwright wants
        milliseconds; keeping its unit here made discover.sitemap_urls (which
        passes timeout=60) time out after 60 ms and report an empty sitemap."""
        self._start()
        self._wait()
        pg = self._page
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            pg.wait_for_timeout(settle_ms)
            html = pg.content()
            if re.search(r"WAFfailover|problema de seguridad|Error de referencia", html, re.I):
                self.errors += 1
                return None
            self.pages += 1
            return html
        except Exception:
            self.errors += 1
            return None

    def text(self, url: str, **kw) -> str | None:
        self._start()
        self._wait()
        pg = self._page
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=kw.get("timeout", 90) * 1000)
            pg.wait_for_timeout(kw.get("settle_ms", 3000))
            return pg.evaluate("document.body?.innerText || ''")
        except Exception:
            self.errors += 1
            return None

    def close(self):
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()

    @property
    def min_gap(self):
        return round(min(self.gaps), 2) if self.gaps else None


SITEMAP_CACHE = pathlib.Path("/tmp/adidas_sitemap.txt")
SITEMAP_TTL_S = 12 * 3600


def discover(fetcher: AdidasFetcher, our_refs: set[str]) -> dict[str, str]:
    """Return {article_code: url} for the products we actually stock.

    Their whole catalogue is irrelevant: we only want the intersection, which
    turns a 15.337-page crawl into a few dozen.
    """
    # The sitemap is ~15s to fetch and changes at most daily; re-reading it on
    # every run is pure overhead during development and repeated crawls.
    txt = None
    if SITEMAP_CACHE.exists() and (time.time() - SITEMAP_CACHE.stat().st_mtime) < SITEMAP_TTL_S:
        txt = SITEMAP_CACHE.read_text(encoding="utf-8")
    if not txt:
        txt = fetcher.text(SITEMAP)
        if txt:
            SITEMAP_CACHE.write_text(txt, encoding="utf-8")
    if not txt:
        return {}
    found: dict[str, str] = {}
    for url in re.findall(r"https://www\.adidas\.es/[^\s<]+?\.html", txt):
        m = CODE_RE.search(url)
        if m:
            code = m.group(1).upper()
            if code in our_refs:
                found.setdefault(code, url)
    return found


def article_code(url: str) -> str | None:
    m = CODE_RE.search(url)
    return m.group(1).upper() if m else None
