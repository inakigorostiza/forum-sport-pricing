#!/usr/bin/env python3
"""The price-scraping agent.

Two phases, because a daily full crawl is not affordable:

  discover  walk the sitemap, fetch candidate pages, extract offers, and record
            which URLs actually match our catalogue. Expensive; runs weekly.
  refresh   re-fetch only the URLs already known to match. Cheap; runs daily.

Offers are APPEND-ONLY: every run adds observations, nothing is overwritten, so
the price history stays intact and any repricing decision is traceable.

  python3 scripts/scraper/run.py --competitor atmosfera-sport --phase discover --limit 300
  python3 scripts/scraper/run.py --competitor atmosfera-sport --phase refresh
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import discover, extract as ex          # noqa: E402
from scraper.fetch import PoliteFetcher, UA_BROWSER, UA_HONEST  # noqa: E402
from supabase_client import Supabase                 # noqa: E402


def load_catalogue(sb: Supabase) -> tuple[set[str], dict[str, str]]:
    """Our GTIN-13 set (the match arbiter) and the mpn-base fallback index."""
    skus = sb.select("skus", select="gtin13")
    gtins = {r["gtin13"] for r in skus if r.get("gtin13")}
    models = sb.select("models", select="ref_prov,brand_code")
    mpn = {}
    for m in models:
        rp = (m.get("ref_prov") or "").upper().strip()
        if rp:
            mpn.setdefault(rp, m["brand_code"])
    return gtins, mpn


def run(competitor: str, phase: str, limit: int | None, dry_run: bool,
        no_cache: bool) -> int:
    sb = Supabase()
    rows = sb.select("competitors", slug=f"eq.{competitor}")
    if not rows:
        sys.exit(f"Unknown competitor: {competitor}")
    c = rows[0]
    if not c["enabled"] and not dry_run:
        sys.exit(f"{competitor} is not enabled. Enable it deliberately, after "
                 f"checking its crawl policy (robots_status={c['robots_status']}).")

    print(f"── {c['name']} · {phase} · delay {c['crawl_delay_s']}s · {c['strategy']}")
    if c["strategy"] == "headless":
        sys.exit("headless strategy not wired yet — see scraper/headless.py")

    fetcher = PoliteFetcher(float(c["crawl_delay_s"]), ua=UA_HONEST,
                            use_cache=not no_cache)
    gtins, mpn_index = load_catalogue(sb)
    print(f"   catalogue: {len(gtins):,} GTIN-13 · {len(mpn_index):,} ref_prov")

    started = datetime.now(timezone.utc)

    # ---- pick the URL set -------------------------------------------------
    if phase == "discover":
        if not c.get("sitemap_url"):
            sys.exit(f"{competitor} has no sitemap_url configured.")
        all_urls = discover.sitemap_urls(fetcher, c["sitemap_url"])
        brands = discover.brand_slugs([b["name"] for b in sb.select("brands", select="name")])
        urls = [u for u in dict.fromkeys(all_urls) if discover.is_candidate(u, brands)]
        print(f"   sitemap: {len(all_urls):,} URLs → {len(urls):,} candidates")
    else:
        known = sb.select("competitor_products",
                          select="url", competitor_slug=f"eq.{competitor}",
                          is_relevant="eq.true")
        urls = [r["url"] for r in known]
        print(f"   refreshing {len(urls):,} known-relevant URLs")

    if limit:
        urls = urls[:limit]
    if not urls:
        print("   nothing to do")
        return 0

    # ---- crawl ------------------------------------------------------------
    products, offers, matched_urls = [], [], set()
    unmatched_offers = 0
    t0 = time.monotonic()
    for i, url in enumerate(urls, 1):
        html = fetcher.get(url)
        if not html:
            continue
        r = ex.extract(html, url)
        page_offers = [o for o in r["offers"] if o["gtin13"] in gtins]
        unmatched_offers += len(r["offers"]) - len(page_offers)
        p = r["product"]
        products.append({
            "competitor_slug": competitor, "url": url,
            "ext_id": p["ext_id"], "title": p["title"],
            "brand_raw": p["brand_raw"], "mpn": p["mpn"],
            "is_relevant": bool(page_offers),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        })
        if page_offers:
            matched_urls.add(url)
            offers.extend((url, o) for o in page_offers)
        if i % 25 == 0 or i == len(urls):
            el = time.monotonic() - t0
            print(f"   {i:>5}/{len(urls)}  matched {len(matched_urls):>4} pages · "
                  f"{len(offers):>5} offers · {el/60:.1f} min", flush=True)

    st = fetcher.stats
    print(f"   fetched {st.pages} · cached {st.from_cache} · errors {st.errors} · "
          f"min gap {st.min_gap}s (configured {c['crawl_delay_s']}s)")
    print(f"   offers matched {len(offers)} · unmatched discarded {unmatched_offers}")

    if dry_run:
        print("   dry-run: nothing written")
        return 0

    # ---- persist ----------------------------------------------------------
    saved = sb.upsert("competitor_products", products,
                      on_conflict="competitor_slug,url", returning=True)
    by_url = {r["url"]: r["id"] for r in saved}

    payload = [{
        "competitor_slug": competitor, "product_id": by_url[url],
        "gtin13": o["gtin13"], "mpn": o["mpn"], "size_raw": o["size_raw"],
        "price": o["price"], "list_price": o["list_price"], "currency": o["currency"],
        "availability": o["availability"], "promo_text": o["promo_text"],
        "shipping_cost": None, "url": o["url"], "raw": o["raw"],
    } for url, o in offers if url in by_url]

    sb.insert("competitor_offers", payload)          # append-only: never upsert
    sb.insert("crawl_log", [{
        "competitor_slug": competitor, "phase": phase,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pages_fetched": st.pages, "offers_found": len(offers) + unmatched_offers,
        "offers_matched": len(payload), "errors": st.errors,
        "min_gap_s": st.min_gap,
        "notes": f"{len(matched_urls)} relevant pages of {len(urls)} crawled",
    }])
    print(f"   wrote {len(saved)} products · {len(payload)} offers")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--competitor", required=True)
    ap.add_argument("--phase", choices=("discover", "refresh"), default="discover")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore the local HTML cache (a refresh needs live prices)")
    a = ap.parse_args()
    raise SystemExit(run(a.competitor, a.phase, a.limit, a.dry_run, a.no_cache))
