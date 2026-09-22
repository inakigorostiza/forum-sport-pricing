"""Find candidate product URLs from a competitor's sitemap.

Discovery is cheap (a handful of sitemap fetches) while crawling is expensive
(one request per page, throttled). So the filtering happens here: narrowing
31.393 sitemap URLs to the few thousand that could plausibly be a men's running
or trail shoe before any product page is fetched.
"""

from __future__ import annotations

import gzip
import re
import unicodedata
import urllib.request

# Sitemap <loc> values, whether or not wrapped in CDATA.
LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", re.S | re.I)

SHOE_WORDS = ("zapatilla", "zapatillas", "shoe", "shoes", "running", "trail",
              "sneaker", "calzado")
# Words that mean it is not the men's running/trail shoe we sell.
EXCLUDE = ("mujer", "woman", "women", "nino", "nina", "junior", "kids", "infantil",
           "camiseta", "pantalon", "sudadera", "calcetin", "mochila", "gorra",
           "chaqueta", "short", "malla", "gafas", "reloj", "bolsa", "guante",
           "padel", "tenis-de-mesa", "futbol", "baloncesto", "bicicleta")


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s)


def _read(fetcher, url: str) -> str | None:
    """Sitemaps are often gzipped, which the HTML fetcher cannot decode."""
    if url.endswith(".gz"):
        from .fetch import SSL, UA_BROWSER
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA_BROWSER})
            with urllib.request.urlopen(req, timeout=40, context=SSL) as r:
                return gzip.decompress(r.read()).decode("utf-8", "ignore")
        except Exception:
            return None
    return fetcher.get(url, timeout=60)


def sitemap_urls(fetcher, sitemap_url: str, *, max_children: int = 12) -> list[str]:
    """Walk a sitemap (or sitemap index) and return every <loc> found."""
    xml = _read(fetcher, sitemap_url)
    if not xml:
        return []
    locs = [m.group(1).strip() for m in LOC_RE.finditer(xml)]
    if not any(u.endswith((".xml", ".xml.gz")) for u in locs):
        return locs                      # a leaf sitemap

    out: list[str] = []
    for child in [u for u in locs if u.endswith((".xml", ".xml.gz"))][:max_children]:
        child_xml = _read(fetcher, child)
        if child_xml:
            out.extend(m.group(1).strip() for m in LOC_RE.finditer(child_xml))
    return out


# A product page ends in its numeric id; category pages ("/brooks-trail-5310")
# also end in digits, so products are additionally required to carry the shop's
# product extension. Without this, ~9 % of candidates were category listings
# that cost a fetch each and yield no offers.
PRODUCT_URL_RE = re.compile(r"-\d{3,}\.html?$", re.I)


def is_candidate(url: str, brands: set[str],
                 product_re: re.Pattern | None = PRODUCT_URL_RE) -> bool:
    """Cheap pre-filter: does this URL look like a men's running/trail shoe of a
    brand we actually stock? Wrong guesses cost only one wasted fetch; the EAN
    match later is the real arbiter."""
    if product_re is not None and not product_re.search(url):
        return False
    s = _slug(url)
    if not any(w in s for w in SHOE_WORDS):
        return False
    if any(w in s for w in EXCLUDE):
        return False
    return any(b in s for b in brands)


def brand_slugs(brand_names: list[str]) -> set[str]:
    """Our brand names as URL-safe fragments, with the obvious aliases the
    catalogue truncates ('SALOM' -> salomon, 'NEW B' -> new-balance)."""
    alias = {"salom": "salomon", "new-b": "new-balance", "sauco": "saucony",
             "mizun": "mizuno", "hoka-one": "hoka", "the-n": "the-north-face",
             "under-ar": "under-armour", "merrel": "merrell", "dynaf": "dynafit",
             "colum": "columbia", "helly": "helly-hansen", "sport": "la-sportiva",
             "hi-te": "hi-tec", "borea": "boreal", "spyro": "spyro"}
    out = set()
    for n in brand_names:
        s = _slug(n).strip("-")
        out.add(alias.get(s, s))
    return {b for b in out if len(b) > 2}
