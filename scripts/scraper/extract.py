"""Turn a product page into normalised offer records.

Structured data first: schema.org JSON-LD is published by every site we crawl
and is far more stable than CSS selectors, which break on every redesign.

Everything here is a pure function of the HTML, so it is testable offline
against a saved page and never needs the network.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                   re.S | re.I)

# Promotion wording worth capturing alongside the price.
PROMO_RE = re.compile(
    r"(-\s?\d{1,2}\s?%|\d{1,2}\s?%\s?(?:dto|descuento|off)"
    r"|2[ªa]\s+unidad|envío\s+gratis|free\s+shipping|black\s+friday|outlet|rebajas)",
    re.I)


def gtin13(value: Any) -> str | None:
    """Normalise any GTIN to 13 digits.

    Both sides of the join must agree: our EANs are stored as 12- or 13-digit
    numbers and competitors publish gtin13, so a 12-digit UPC is left-padded.
    A 14-digit GTIN-14 with a leading zero is trimmed back to 13.
    """
    if value in (None, ""):
        return None
    d = re.sub(r"\D", "", str(value))
    if len(d) == 14 and d[0] == "0":
        d = d[1:]
    if len(d) == 12:
        d = "0" + d
    return d if len(d) == 13 else None


def price(value: Any) -> float | None:
    """Parse a price that may arrive as 112.5, '112,50', '1.234,56 €' or '€112.50'."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    s = re.sub(r"[^\d.,]", "", str(value))
    if not s:
        return None
    if "," in s and "." in s:
        # whichever separator is last is the decimal one
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") \
            else s.replace(",", "")
    elif "," in s:
        # a lone comma is decimal in es-ES unless it groups thousands (1,234)
        s = s.replace(",", "") if re.search(r",\d{3}$", s) else s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


# Containers that wrap the real Product rather than being one. Tradeinn nests
# its ProductGroup inside WebPage.mainEntity, so a parser that only looks at
# top-level nodes sees an Organization and a WebPage and reports "no offers".
_WRAPPERS = ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement", "item")


def _ld_nodes(html: str) -> Iterator[dict]:
    """Yield every JSON-LD object, descending through the usual wrappers."""
    for m in LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        seen = 0
        while stack and seen < 2000:          # cheap guard against a cyclic graph
            node = stack.pop()
            seen += 1
            if not isinstance(node, dict):
                continue
            for key in _WRAPPERS:
                child = node.get(key)
                if isinstance(child, list):
                    stack.extend(c for c in child if isinstance(c, dict))
                elif isinstance(child, dict):
                    stack.append(child)
            yield node


def _types(node: dict) -> set[str]:
    t = node.get("@type") or []
    return {str(x) for x in (t if isinstance(t, list) else [t])}


def _first_offer(node: dict) -> dict:
    off = node.get("offers")
    if isinstance(off, list):
        return next((o for o in off if isinstance(o, dict)), {})
    return off if isinstance(off, dict) else {}


def _brand(node: dict) -> str | None:
    b = node.get("brand")
    if isinstance(b, dict):
        return b.get("name")
    return b if isinstance(b, str) else None


def extract(html: str, url: str) -> dict:
    """Return {product: {...}, offers: [...]} from a product page.

    Handles both shapes seen in the wild: a ProductGroup whose hasVariant list
    carries one entry per size, and a plain Product.
    """
    product: dict = {"url": url, "ext_id": None, "title": None,
                     "brand_raw": None, "mpn": None}
    offers: list[dict] = []
    promo_page = PROMO_RE.search(re.sub(r"<[^>]+>", " ", html[:200_000]))
    promo_page = promo_page.group(0).strip() if promo_page else None

    def add(node: dict, parent: dict | None = None) -> None:
        off = _first_offer(node)
        p = price(off.get("price") or off.get("lowPrice"))
        if p is None:
            return
        list_p = price(off.get("highPrice")) or price(
            (off.get("priceSpecification") or {}).get("price")
            if isinstance(off.get("priceSpecification"), dict) else None)
        offers.append({
            "gtin13": gtin13(node.get("gtin13") or node.get("gtin")
                             or node.get("gtin14") or node.get("gtin12")),
            "mpn": node.get("mpn") or (parent or {}).get("mpn"),
            "size_raw": str(node.get("size")) if node.get("size") is not None else None,
            "price": p,
            "list_price": list_p if (list_p and list_p > p) else None,
            "currency": (off.get("priceCurrency") or "EUR")[:3],
            "availability": off.get("availability"),
            "promo_text": promo_page,
            "url": off.get("url") or url,
            "raw": node,
        })

    for node in _ld_nodes(html):
        ts = _types(node)
        if "ProductGroup" in ts:
            product.update({
                "ext_id": str(node.get("productGroupID") or node.get("sku") or "") or None,
                "title": node.get("name"),
                "brand_raw": _brand(node),
                "mpn": node.get("mpn"),
            })
            for v in node.get("hasVariant") or []:
                if isinstance(v, dict):
                    add(v, node)
        elif "Product" in ts:
            product.update({
                "ext_id": product["ext_id"] or str(node.get("sku") or "") or None,
                "title": product["title"] or node.get("name"),
                "brand_raw": product["brand_raw"] or _brand(node),
                "mpn": product["mpn"] or node.get("mpn"),
            })
            add(node)

    # De-duplicate: the same variant can appear in both a ProductGroup and a
    # standalone Product node on the same page.
    seen, unique = set(), []
    for o in offers:
        k = (o["gtin13"], o["size_raw"], o["price"])
        if k not in seen:
            seen.add(k)
            unique.append(o)
    return {"product": product, "offers": unique}
