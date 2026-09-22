#!/usr/bin/env python3
"""Evaluate whether a competitor can be crawled, and how.

Runs the same five questions against every site, in the same order, and records
the answer — so "we can't scrape X" is a finding with evidence behind it rather
than an impression:

  1. Does robots.txt come back over plain HTTP?      (reachable at all)
  2. Does it declare a sitemap, and can we read it?  (discovery)
  3. Do any URLs look like running/trail shoes?      (relevance)
  4. Does a product page carry structured data?      (extraction)
  5. Does anything match our catalogue?              (usefulness)

Plain HTTP first; a site that refuses it is retried with patchright, because
that is the expensive path and should only be used where it is needed.

  python3 scripts/scraper/evaluate.py                    # every pending site
  python3 scripts/scraper/evaluate.py --only wala,base   # named sites
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import discover                              # noqa: E402
from scraper.extract import extract                       # noqa: E402
from scraper.fetch import PoliteFetcher, UA_BROWSER       # noqa: E402
from supabase_client import Supabase                      # noqa: E402

OUT = Path(__file__).resolve().parent.parent.parent / "data" / "evaluation.json"

# Aggregators and comparison engines resell other shops' listings rather than
# holding a price of their own, so they are out of scope by definition.
SKIP = {"google-shopping", "amazon", "zalando", "asos"}

SHOE = re.compile(r"zapatilla|shoe|chaussure|schuh|sneaker|calzado|footwear", re.I)
RUN  = re.compile(r"running|trail|correr|laufschuh", re.I)
EXCL = re.compile(r"mujer|woman|women|damen|femme|nino|nina|kids|junior|infantil|"
                  r"camiseta|pantalon|sudadera|chaqueta|calcetin|mochila|gorra|"
                  r"short|malla|guante|gafas|reloj|bolsa|casco|bicicleta|bike", re.I)


def probe(slug: str, comp: dict, gtins: set, refs: set, use_browser: bool) -> dict:
    r = {"slug": slug, "name": comp["name"], "records_ref": comp.get("records_ref"),
         "method": "patchright" if use_browser else "http",
         "robots": None, "sitemap": None, "urls": 0, "candidates": 0,
         "pages_ok": 0, "offers": 0, "with_gtin": 0, "with_mpn": 0, "matched": 0,
         "sample": None, "verdict": None, "note": ""}

    if use_browser:
        from scraper.sites.adidas import AdidasFetcher
        f = AdidasFetcher(3.0)
        get = lambda u, **k: f.get(u, settle_ms=2500)
        text = lambda u: f.text(u, settle_ms=3000)
    else:
        f = PoliteFetcher(1.5, ua=UA_BROWSER, use_cache=True, respect_robots=False)
        get = lambda u, **k: f.get(u, timeout=k.get("timeout", 25))
        text = get

    try:
        base = comp["base_url"].rstrip("/")
        robots = text(base + "/robots.txt")
        if not robots or "<html" in robots[:400].lower():
            r["robots"] = "blocked"
            r["verdict"] = "BLOCKED" if not use_browser else "BLOCKED (even with browser)"
            return r
        r["robots"] = "ok"
        sms = [l.split(":", 1)[1].strip() for l in robots.splitlines()
               if l.lower().startswith("sitemap")]
        if not sms:
            r["verdict"] = "NO SITEMAP"
            r["note"] = "no sitemap declared; discovery would have to go via category pages"
            return r
        r["sitemap"] = sms[0]

        urls = []
        for sm in sms[:3]:
            urls += discover.sitemap_urls(f, sm, max_children=6)
            if len(urls) > 60000:
                break
        r["urls"] = len(urls)
        if not urls:
            # robots.txt was served but the sitemap itself was refused: that is a
            # block, not an empty catalogue, and must not read as "no candidates".
            r["verdict"] = "SITEMAP UNREADABLE"
            r["note"] = f"robots.txt declares {len(sms)} sitemap(s) but none returns URLs"
            return r
        cands = [u for u in dict.fromkeys(urls)
                 if SHOE.search(u) and RUN.search(u) and not EXCL.search(u)]
        if not cands:   # some shops do not put "running" in the slug
            cands = [u for u in dict.fromkeys(urls) if SHOE.search(u) and not EXCL.search(u)]
        r["candidates"] = len(cands)
        if not cands:
            r["verdict"] = "NO SHOE URLS"
            r["note"] = f"{len(urls)} sitemap URLs, none looks like a shoe"
            return r

        for u in cands[:6]:
            h = get(u, timeout=30)
            if not h:
                continue
            r["pages_ok"] += 1
            ex = extract(h, u)
            offs = ex["offers"]
            r["offers"] += len(offs)
            r["with_gtin"] += sum(1 for o in offs if o["gtin13"])
            r["with_mpn"] += sum(1 for o in offs if o["mpn"])
            r["matched"] += sum(1 for o in offs
                                if o["gtin13"] in gtins
                                or (o["mpn"] or "").upper().split("-")[0] in refs)
            if offs and not r["sample"]:
                r["sample"] = {"url": u, **{k: offs[0][k] for k in
                               ("gtin13", "mpn", "size_raw", "price")}}
            if r["matched"]:
                break

        if r["matched"]:
            r["verdict"] = "VIABLE · matches found"
        elif r["with_gtin"] or r["with_mpn"]:
            r["verdict"] = "VIABLE · no matches in sample"
            r["note"] = "publishes a match key; the catalogue may simply not overlap"
        elif r["offers"]:
            r["verdict"] = "NO MATCH KEY"
            r["note"] = "prices present but neither gtin13 nor mpn: nothing to join on"
        else:
            r["verdict"] = "NO STRUCTURED DATA"
            r["note"] = "no usable JSON-LD; most likely rendered client-side"
    except Exception as e:
        r["verdict"] = "ERROR"
        r["note"] = f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        if use_browser:
            try: f.close()
            except Exception: pass
    return r


# Best to worst. The browser retry is only accepted when it moves UP this list:
# otherwise a failed browser attempt silently buries a good HTTP result.
RANK = ["VIABLE · matches found", "VIABLE · no matches in sample",
        "NO MATCH KEY", "NO STRUCTURED DATA", "NO SHOE URLS",
        "SITEMAP UNREADABLE", "NO SITEMAP", "BLOCKED",
        "BLOCKED (even with browser)", "ERROR"]
rank = lambda v: RANK.index(v) if v in RANK else len(RANK)


def main(only: list[str] | None, retry_browser: bool) -> int:
    sb = Supabase()
    gtins = {r["gtin13"] for r in sb.select("skus", select="gtin13")}
    refs = {(m["ref_prov"] or "").upper() for m in sb.select("models", select="ref_prov")}
    comps = {c["slug"]: c for c in sb.select("competitors")}
    done = {r["competitor_slug"] for r in sb.select("crawl_log", select="competitor_slug")}

    todo = [s for s in comps if s not in SKIP and s not in done]
    if only:
        todo = [s for s in todo if s in only] or [s for s in comps if s in only]
    todo.sort(key=lambda s: -(comps[s].get("records_ref") or 0))
    print(f"evaluating {len(todo)} competitors\n")

    results = []
    for i, slug in enumerate(todo, 1):
        r = probe(slug, comps[slug], gtins, refs, use_browser=False)
        if retry_browser and r["verdict"] in (
                "BLOCKED", "NO STRUCTURED DATA", "SITEMAP UNREADABLE"):
            r2 = probe(slug, comps[slug], gtins, refs, use_browser=True)
            if rank(r2["verdict"]) < rank(r["verdict"]):
                r2["note"] = (r2["note"] + " · needs a browser").strip(" ·")
                r = r2
            else:
                r["note"] = (r["note"] + " · browser did not help").strip(" ·")
        results.append(r)
        print(f"{i:>2}/{len(todo)} {r['name'][:30]:32} {r['verdict']:38} "
              f"urls={r['urls']:>6} cand={r['candidates']:>5} "
              f"offers={r['offers']:>3} gtin={r['with_gtin']:>3} match={r['matched']}",
              flush=True)
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated slugs")
    ap.add_argument("--no-browser", action="store_true",
                    help="skip the patchright retry for blocked sites")
    a = ap.parse_args()
    raise SystemExit(main(a.only.split(",") if a.only else None, not a.no_browser))
