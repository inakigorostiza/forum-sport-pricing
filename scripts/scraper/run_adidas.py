#!/usr/bin/env python3
"""Crawl adidas.es for the models we stock.

Separate from run.py because adidas needs a different browser stack (patchright),
a different matching key (article code, not GTIN) and a much smaller, targeted
URL set. Everything downstream — storage, matching, the comparison views — is
shared.

  python3 scripts/scraper/run_adidas.py --limit 20 --dry-run
  python3 scripts/scraper/run_adidas.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import extract as ex                      # noqa: E402
from scraper.sites.adidas import AdidasFetcher, discover, article_code  # noqa: E402
from supabase_client import Supabase                   # noqa: E402

SLUG = "adidas"


def main(limit: int | None, dry_run: bool) -> int:
    sb = Supabase()
    c = sb.select("competitors", slug=f"eq.{SLUG}")
    if not c:
        sys.exit("adidas is not seeded. Run scripts/seed_competitors.py first.")
    c = c[0]
    if not c["enabled"] and not dry_run:
        sys.exit("adidas is not enabled. Enable it deliberately: it is behind a WAF "
                 "and the crawl should stay small and slow.")

    models = sb.select("models", select="modelo,ref_prov", brand_code="eq.ADIDAS")
    refs = {m["ref_prov"].upper(): m["modelo"] for m in models if m.get("ref_prov")}
    print(f"── adidas · {len(refs)} article codes in our catalogue "
          f"· delay {c['crawl_delay_s']}s")

    f = AdidasFetcher(float(c["crawl_delay_s"]))
    started = datetime.now(timezone.utc)
    try:
        targets = discover(f, set(refs))
        print(f"   their sitemap ∩ our catalogue: {len(targets)} products")
        items = sorted(targets.items())[:limit] if limit else sorted(targets.items())

        products, offers = [], []
        for i, (code, url) in enumerate(items, 1):
            html = f.get(url)
            if not html:
                print(f"   {i:>3}/{len(items)}  {code}  BLOCKED/ERROR")
                continue
            r = ex.extract(html, url)
            # adidas publishes no GTIN; the article code is the join key, and it
            # comes from the URL, which is more reliable than anything in-page.
            page = [o for o in r["offers"] if o["price"]]
            for o in page:
                o["gtin13"] = None
                o["mpn"] = code
            products.append({
                "competitor_slug": SLUG, "url": url,
                "ext_id": r["product"]["ext_id"], "title": r["product"]["title"],
                "brand_raw": r["product"]["brand_raw"] or "adidas", "mpn": code,
                "is_relevant": bool(page),
                "last_seen": datetime.now(timezone.utc).isoformat(),
            })
            offers.extend((url, o) for o in page)
            price = min((o["price"] for o in page), default=None)
            print(f"   {i:>3}/{len(items)}  {code}  {len(page):>2} tallas  "
                  f"{price if price is not None else '-'} €  {(r['product']['title'] or '')[:40]}",
                  flush=True)
    finally:
        f.close()

    print(f"   fetched {f.pages} · errors {f.errors} · min gap {f.min_gap}s "
          f"(configured {c['crawl_delay_s']}s)")
    if dry_run:
        print("   dry-run: nothing written")
        return 0
    if not products:
        print("   nothing to write")
        return 1

    saved = sb.upsert("competitor_products", products,
                      on_conflict="competitor_slug,url", returning=True)
    by_url = {r["url"]: r["id"] for r in saved}
    payload = [{
        "competitor_slug": SLUG, "product_id": by_url[u],
        "gtin13": None, "mpn": o["mpn"], "size_raw": o["size_raw"],
        "price": o["price"], "list_price": o["list_price"], "currency": o["currency"],
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
        "notes": f"article-code match; {len(products)} products",
    }])
    n = sb.rpc("refresh_comparativa_publica")
    print(f"   wrote {len(saved)} products · {len(payload)} offers · "
          f"public comparison now {n} models")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    raise SystemExit(main(a.limit, a.dry_run))
