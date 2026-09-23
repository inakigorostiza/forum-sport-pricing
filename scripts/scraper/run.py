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
import re
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


def _code_match(offer: dict, mpn_index: dict) -> bool:
    """Does this offer's article code name one of our models?

    Accept the full code and the part before the first hyphen, because the two
    sides carry colour differently: our Saucony ref_prov keeps the suffix
    (S29101-01) while our Nike ref_prov does not (CD4371). Matching only the
    base loses the first; matching only the full value loses the second.
    """
    code = (offer.get("mpn") or "").upper().strip()
    return bool(code) and (code in mpn_index
                           or code.split("-")[0] in mpn_index)


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
    # Client-rendered shops need a real browser: plain HTTP returns the shell
    # and the extractor correctly reports "no offers". Patchright is the only
    # stack tested that is not detected.
    if c["strategy"] == "headless":
        from scraper.sites.adidas import AdidasFetcher
        fetcher = AdidasFetcher(float(c["crawl_delay_s"]))
    else:
        fetcher = PoliteFetcher(
            float(c["crawl_delay_s"]),
            ua=UA_BROWSER if c.get("user_agent") == "browser" else UA_HONEST,
            use_cache=not no_cache)
    gtins, mpn_index = load_catalogue(sb)
    print(f"   catalogue: {len(gtins):,} GTIN-13 · {len(mpn_index):,} ref_prov")

    started = datetime.now(timezone.utc)

    # ---- pick the URL set -------------------------------------------------
    if phase == "discover":
        if not c.get("sitemap_url"):
            sys.exit(f"{competitor} has no sitemap_url configured.")
        all_urls = discover.sitemap_urls(
            fetcher, c["sitemap_url"],
            max_children=c.get("sitemap_max_children") or 12)
        brands = discover.brand_slugs([b["name"] for b in sb.select("brands", select="name")])
        # Product URL shape is per shop; without it the crawler burns requests on
        # category pages (Atmósfera) or rejects everything (bergfreunde, /p/, ...).
        pat = re.compile(c["product_url_re"]) if c.get("product_url_re") else None
        need_brand = c.get("classification") != "Marca"
        urls = [u for u in dict.fromkeys(all_urls)
                if discover.is_candidate(u, brands, product_re=pat,
                                         require_brand=need_brand)]
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
        p = r["product"]
        # Shops that publish no GTIN still publish the manufacturer style code:
        # the Emotion family exposes it as JSON-LD "sku" ("DJ7883-114"), whose
        # base is exactly our ref_prov. Carry it onto the offer so the stored
        # row keeps the key it matched on.
        for o in r["offers"]:
            if not o.get("mpn") and p.get("ext_id"):
                o["mpn"] = p["ext_id"]
        page_offers = [o for o in r["offers"]
                       if o["gtin13"] in gtins or _code_match(o, mpn_index)]
        unmatched_offers += len(r["offers"]) - len(page_offers)
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

    st = fetcher.stats if hasattr(fetcher, "stats") else None
    if st is not None:
        print(f"   fetched {st.pages} · cached {st.from_cache} · errors {st.errors} · "
              f"min gap {st.min_gap}s (configured {c['crawl_delay_s']}s)")
    else:                       # the browser fetcher keeps its counters inline
        print(f"   fetched {fetcher.pages} · errors {fetcher.errors} · "
              f"min gap {fetcher.min_gap}s (configured {c['crawl_delay_s']}s)")
        class _S: pass
        st = _S(); st.pages = fetcher.pages; st.errors = fetcher.errors
        st.from_cache = 0; st.min_gap = fetcher.min_gap
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

    # Rebuild the narrow public slice the landing page reads. Doing it here
    # means the page never joins across the whole offer history, and never
    # needs read access to the private competitor tables.
    if hasattr(fetcher, "close"):
        try: fetcher.close()
        except Exception: pass
    n = sb.rpc("refresh_comparativa_publica")
    print(f"   public comparison refreshed: {n} models")
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
