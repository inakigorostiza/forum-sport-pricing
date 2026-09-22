"""Polite HTTP fetching.

Politeness is enforced here rather than left to each site module, so it cannot
be forgotten: one request at a time per host, never faster than the configured
crawl delay, robots.txt honoured where it is readable, and every gap recorded
so the crawl can be audited afterwards.
"""

from __future__ import annotations

import gzip
import hashlib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = ROOT / "data" / "cache"

# An honest, identifiable agent for sites that permit crawling: they can see who
# we are and block us by name if they would rather not be monitored.
UA_HONEST = ("ForumSportPriceMonitor/1.0 "
             "(+https://www.forumsport.com; competitive price monitoring)")
# Only for hosts already configured as `headless`, where an identifiable agent
# is refused outright.
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")


def _ssl_context() -> ssl.SSLContext:
    """Same trap as the Supabase loader: python.org builds on macOS carry no
    root certificates, so every HTTPS fetch dies with CERTIFICATE_VERIFY_FAILED
    until certifi's bundle is supplied explicitly."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL = _ssl_context()


@dataclass
class FetchStats:
    pages: int = 0
    errors: int = 0
    from_cache: int = 0
    gaps: list[float] = field(default_factory=list)
    last_error: str | None = None

    @property
    def min_gap(self) -> float | None:
        return round(min(self.gaps), 2) if self.gaps else None


class PoliteFetcher:
    def __init__(self, delay_s: float, *, ua: str = UA_HONEST, use_cache: bool = True,
                 respect_robots: bool = True):
        self.delay = float(delay_s)
        self.ua = ua
        self.use_cache = use_cache
        self.respect_robots = respect_robots
        self.stats = FetchStats()
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        CACHE.mkdir(parents=True, exist_ok=True)

    # -- robots ----------------------------------------------------------
    def _robots_for(self, url: str):
        host = urllib.parse.urlsplit(url)._replace(path="", query="", fragment="").geturl()
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(host + "/robots.txt")
            try:
                rp.read()
            except Exception:
                rp = None          # unreadable (403/timeout): decided by policy, not guessed
            self._robots[host] = rp
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(self.ua, url)

    # -- throttle --------------------------------------------------------
    def _wait(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        prev = self._last.get(host)
        now = time.monotonic()
        if prev is not None:
            gap = now - prev
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self.stats.gaps.append(round(time.monotonic() - prev, 2))
        self._last[host] = time.monotonic()

    # -- fetch -----------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        return CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".html")

    def get(self, url: str, *, timeout: int = 30) -> str | None:
        cp = self._cache_path(url)
        if self.use_cache and cp.exists():
            self.stats.from_cache += 1
            return cp.read_text(encoding="utf-8", errors="ignore")

        if not self.allowed(url):
            self.stats.errors += 1
            self.stats.last_error = f"robots.txt disallows {url}"
            return None

        self._wait(url)
        req = urllib.request.Request(url, headers={
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                html = raw.decode("utf-8", "ignore")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            # Never fail silently: a swallowed error looks identical to "the page
            # had no offers", which is how a broken crawl reports success.
            self.stats.errors += 1
            self.stats.last_error = f"{type(e).__name__}: {e}"
            return None

        self.stats.pages += 1
        if self.use_cache:
            cp.write_text(html, encoding="utf-8")
        return html
