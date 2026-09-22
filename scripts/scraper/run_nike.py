#!/usr/bin/env python3
"""Crawl nike.com/es for the models we stock.

Same shape as run_adidas.py, with one structural difference: Nike's URLs carry
no style code, so the crawl set cannot be narrowed to our catalogue in advance.
Candidates are filtered on slug words and the match is decided after fetching —
which also means one page can yield several of our models, since Nike lists all
colourways of a style on one page.

  python3 scripts/scraper/run_nike.py --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import extract as ex                       # noqa: E402
from scraper.sites.adidas import AdidasFetcher as Patchright   # noqa: E402
from scraper.sites.nike import discover, style_base     # noqa: E402
from supabase_client import Supabase                    # noqa: E402

SLUG = "nike"


def main(limit: int | None, dry_run: bool) -> int:
    sb = Supabase()
    rows = sb.select("competitors", slug=f"eq.{SLUG}")
    if not rows:
        sys.exit("nike is not seeded. Run scripts/seed_competitors.py first.")
    c = rows[0]
    if not c["enabled"] and not dry_run:
        sys.exit("nike is not enabled; enable it deliberately.")

    models = sb.select("models", select="modelo,ref_prov", brand_code="eq.NIKE")
    refs = {m["ref_prov"].upper() for m in models if m.get("ref_prov")}
    print(f"── Nike · {len(refs)} style codes in our catalogue · delay {c['crawl_delay_s']}s")

    f = Patchright(float(c["crawl_delay_s"]))
    started = datetime.now(timezone.utc)
    products, offers = [], []
    try:
        urls = discover(f)
        print(f"   candidate shoe URLs: {len(urls)}")
        urls = urls[:limit] if limit else urls
        for i, u in enumerate(urls, 1):
            html = f.get(u)
            if not html:
                print(f"   {i:>3}/{len(urls)}  BLOCKED/ERROR")
                continue
            r = ex.extract(html, u)
            # Keep only colourways whose style base is in our catalogue.
            page = [o for o in r["offers"]
                    if o["price"] and style_base(o["mpn"]) in refs]
            for o in page:
                o["gtin13"] = None
                o["mpn"] = style_base(o["mpn"])
            if page:
                products.append({
                    "competitor_slug": SLUG, "url": u,
                    "ext_id": r["product"]["ext_id"], "title": r["product"]["title"],
                    "brand_raw": "Nike", "mpn": page[0]["mpn"], "is_relevant": True,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                })
                offers.extend((u, o) for o in page)
            hit = {o["mpn"] for o in page}
            print(f"   {i:>3}/{len(urls)}  {len(page):>2} match  {','.join(sorted(hit)) or '-':<22}"
                  f"{(r['product']['title'] or '')[:38]}", flush=True)
    finally:
        f.close()

    print(f"   fetched {f.pages} · errors {f.errors} · min gap {f.min_gap}s")
    if dry_run:
        print("   dry-run: nothing written"); return 0
    if not products:
        print("   no matches to write"); return 0

    saved = sb.upsert("competitor_products", products,
                      on_conflict="competitor_slug,url", returning=True)
    by_url = {r["url"]: r["id"] for r in saved}
    payload = [{
        "competitor_slug": SLUG, "product_id": by_url[u], "gtin13": None,
        "mpn": o["mpn"], "size_raw": o["size_raw"], "price": o["price"],
        "list_price": o["list_price"], "currency": o["currency"],
        "availability": o["availability"], "promo_text": o["promo_text"],
        "shipping_cost": None, "url": o["url"], "raw": o["raw"],
    } for u, o in offers if u in by_url]
    sb.insert("competitor_offers", payload)
    sb.insert("crawl_log", [{
        "competitor_slug": SLUG, "phase": "discover",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pages_fetched": f.pages, "offers_found": len(offers),
        "offers_matched": len(payload), "errors": f.errors, "min_gap_s": f.min_gap,
        "notes": "style-code (mpn base) match",
    }])
    n = sb.rpc("refresh_comparativa_publica")
    print(f"   wrote {len(saved)} products · {len(payload)} offers · comparison now {n} models")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    raise SystemExit(main(a.limit, a.dry_run))
