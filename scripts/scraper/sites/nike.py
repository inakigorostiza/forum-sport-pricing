"""nike.com/es — targeted scraper.

Reuses the patchright fetcher built for adidas; Nike sits behind similar
protection (plain curl gets 403 on robots.txt) and the same persistent-context
browser clears it.

Two differences from adidas shape the discovery:

1. **The style code is not in the URL.** adidas URLs end in the article code;
   Nike's are opaque slugs (/es/t/acg-pegasus-trail-...-edJ7MX66), so the
   catalogue cannot be pre-filtered by code. Filtering is on the slug words
   instead, and the match is decided after fetching.

2. **The match key is `mpn`, with a colour suffix.** Nike's JSON-LD publishes
   mpn as style-colour ("HV8116-001"); our ref_prov stores the 6-character style
   base ("HV8116"). Stripping at the dash joins them. One Nike page carries
   several colourways, so one fetch can yield several of our models.

Nike's robots.txt (at the root, not /es/) declares sitemap-v2-pdp-index.xml and
places no disallow on /t/ product pages.
"""

from __future__ import annotations

import pathlib
import re
import time

SITEMAP = "https://www.nike.com/sitemap-v2-pdp-es-es.xml"
CACHE = pathlib.Path("/tmp/nike_sitemap_urls.txt")
CACHE_TTL_S = 12 * 3600
LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", re.S)

# Slug words that mark a running or trail shoe. Deliberately broad: a wrong
# guess costs one fetch, while a missed product is invisible.
SHOE = re.compile(r"zapatilla", re.I)
RUN = re.compile(r"running|trail|pegasus|vomero|invincible|structure|winflo|juniper|"
                 r"zegama|alphafly|vaporfly|streakfly|infinity|revolution|downshifter|"
                 r"terra|ultrafly|zoomx|interact", re.I)
EXCLUDE = re.compile(r"mujer|nino|nina|infantil|junior|camiseta|pantalon|sudadera|"
                     r"chaqueta|calcetin|mochila|gorra|short|malla", re.I)

MPN_RE = re.compile(r"^([A-Z0-9]{6})-(\d{3})$")


def style_base(mpn: str | None) -> str | None:
    """'HV8116-001' -> 'HV8116'. Our ref_prov holds the style without colour."""
    if not mpn:
        return None
    m = MPN_RE.match(mpn.strip().upper())
    return m.group(1) if m else (mpn.strip().upper() if len(mpn.strip()) == 6 else None)


def discover(fetcher) -> list[str]:
    """Men's running/trail shoe URLs from the Spanish PDP sitemap (~24 MB)."""
    if CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < CACHE_TTL_S:
        return [u for u in CACHE.read_text(encoding="utf-8").splitlines() if u]

    xml = fetcher.get(SITEMAP, settle_ms=6000, timeout=120000)
    if not xml:
        return []
    urls = LOC_RE.findall(xml)
    keep = [u for u in urls
            if SHOE.search(u) and RUN.search(u) and not EXCLUDE.search(u)]
    CACHE.write_text("\n".join(keep), encoding="utf-8")
    return keep
