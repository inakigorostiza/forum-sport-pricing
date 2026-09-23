#!/usr/bin/env python3
"""Crawl salomon.com/es-es for the models we stock.

Salomon needs its own runner for three reasons:

1. **robots.txt declares no sitemap**, but `/sitemap.xml` exists anyway with 42
   children, including an API endpoint that returns the Spanish product list:
   `/api/sitemap/products?locale=es-es` (1.190 URLs). "No sitemap declared" is
   not the same as "no sitemap".

2. **Product URLs carry no usable code.** They end in a short internal id
   (`speedcross-6-gore-tex-lg9214`) unrelated to our `ref_prov`, so the crawl
   set is narrowed by matching our model NAMES against the slug instead.

3. **No gtin13, and the code is only in the page body.** Their JSON-LD carries a
   single model-level offer with no identifier, but the page text contains the
   manufacturer references (`L41738600`) that our catalogue stores as
   `ref_prov`. So the match key is scraped from the HTML rather than read from a
   field — and one page can carry several colourways, each a different model of
   ours at the same price.

  python3 scripts/scraper/run_salomon.py --limit 20 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import discover                              # noqa: E402
from scraper import extract as ex                         # noqa: E402
from scraper.fetch import PoliteFetcher, UA_BROWSER       # noqa: E402
from supabase_client import Supabase                      # noqa: E402

SLUG = "salomon"
SITEMAP = "https://www.salomon.com/api/sitemap/products?locale=es-es"
# Salomon references look like L41738600 — a letter and 6-8 digits.
CODE_RE = re.compile(r"\b([A-Z]\d{6,8})\b")
EXCL = re.compile(r"woman|women|mujer|kid|junior|nino", re.I)


def main(limit: int | None, dry_run: bool) -> int:
    sb = Supabase()
    rows = sb.select("competitors", slug=f"eq.{SLUG}")
    if not rows:
        sys.exit("salomon is not seeded.")
    c = rows[0]
    if not c["enabled"] and not dry_run:
        sys.exit("salomon is not enabled; enable it deliberately.")

    models = sb.select("models", select="modelo,ref_prov,nombre_modelo", brand_code="eq.SALOM")
    refs = {m["ref_prov"].upper(): m["modelo"] for m in models if m.get("ref_prov")}
    names = {w for m in models for w in (m["nombre_modelo"] or "").lower().split()[:1] if len(w) > 3}
    print(f"── Salomon · {len(refs)} references · delay {c['crawl_delay_s']}s")

    f = PoliteFetcher(float(c["crawl_delay_s"]), ua=UA_BROWSER, use_cache=False,
                      respect_robots=False)
    started = datetime.now(timezone.utc)
    urls = discover.sitemap_urls(f, SITEMAP)
    cand = [u for u in urls if any(n in u.lower() for n in names) and not EXCL.search(u)]
    print(f"   sitemap {len(urls):,} URLs → {len(cand):,} candidates")
    cand = cand[:limit] if limit else cand

    products, offers = [], []
    for i, u in enumerate(cand, 1):
        html = f.get(u, timeout=30)
        if not html:
            continue
        r = ex.extract(html, u)
        price = min((o["price"] for o in r["offers"] if o["price"]), default=None)
        if price is None:
            continue
        # The match key is in the page body, not in any field.
        hits = {c_ for c_ in CODE_RE.findall(html.upper()) if c_ in refs}
        if not hits:
            continue
        products.append({
            "competitor_slug": SLUG, "url": u,
            "ext_id": r["product"]["ext_id"], "title": r["product"]["title"],
            "brand_raw": "Salomon", "mpn": sorted(hits)[0], "is_relevant": True,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        })
        for code in sorted(hits):
            offers.append((u, {"gtin13": None, "mpn": code, "size_raw": None,
                               "price": price, "list_price": None, "currency": "EUR",
                               "availability": r["offers"][0].get("availability"),
                               "promo_text": r["offers"][0].get("promo_text"),
                               "url": u, "raw": {"codes": sorted(hits)}}))
        print(f"   {i:>4}/{len(cand)}  {','.join(sorted(hits)):<24} {price} €  "
              f"{(r['product']['title'] or '')[:34]}", flush=True)

    st = f.stats
    print(f"   fetched {st.pages} · errors {st.errors} · min gap {st.min_gap}s")
    if dry_run:
        print("   dry-run: nothing written"); return 0
    if not products:
        print("   no matches"); return 0

    saved = sb.upsert("competitor_products", products,
                      on_conflict="competitor_slug,url", returning=True)
    by = {r["url"]: r["id"] for r in saved}
    payload = [{"competitor_slug": SLUG, "product_id": by[u], "gtin13": None,
                "mpn": o["mpn"], "size_raw": None, "price": o["price"],
                "list_price": None, "currency": "EUR", "availability": o["availability"],
                "promo_text": o["promo_text"], "shipping_cost": None,
                "url": o["url"], "raw": o["raw"]}
               for u, o in offers if u in by]
    sb.insert("competitor_offers", payload)
    sb.insert("crawl_log", [{"competitor_slug": SLUG, "phase": "discover",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pages_fetched": st.pages, "offers_found": len(offers),
        "offers_matched": len(payload), "errors": st.errors, "min_gap_s": st.min_gap,
        "notes": "reference scraped from page body; model-level match"}])
    n = sb.rpc("refresh_comparativa_publica")
    print(f"   wrote {len(saved)} products · {len(payload)} offers · comparison now {n} rows")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    raise SystemExit(main(a.limit, a.dry_run))
