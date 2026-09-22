#!/usr/bin/env python3
"""Seed the `competitors` table from the source competitor list.

Crawl policy per site was established by actually fetching each robots.txt —
see SCRAPING.md. Nothing is enabled by default: `enabled` is set deliberately,
one site at a time, after its policy has been read.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supabase_client import Supabase  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "dataset" / "Competidores_PricingDinamico.xlsx"

# Measured, not assumed — each of these was fetched (2026-09-22):
#   allowed      robots.txt readable and product paths permitted
#   blocked_403  the site refuses automated requests outright, robots.txt included
POLICY = {
    "atmosfera-sport": dict(strategy="sitemap_jsonld", crawl_delay_s=2.0, robots_status="allowed",
                            sitemap_url="https://www.atmosferasport.es/1_index_sitemap.xml",
                            notes="JSON-LD ProductGroup with hasVariant[].gtin13 + mpn + offers. Reference implementation."),
    "decathlon":       dict(strategy="sitemap_jsonld", crawl_delay_s=5.0, robots_status="allowed",
                            sitemap_url="https://www.decathlon.es/sitemap-index.xml",
                            notes="robots.txt publishes Crawl-delay 2-5; we use the most conservative."),
    "tradeinn":        dict(strategy="sitemap_jsonld", crawl_delay_s=2.0, robots_status="allowed",
                            sitemap_url="https://www.tradeinn.com/runnerinn/sitemaps/sitemap-runnerinn.xml",
                            notes="Disallow:/ applies only to EtaoSpider. Many path-level disallows to honour."),
    "running-emotion": dict(strategy="sitemap_jsonld", crawl_delay_s=2.0, robots_status="allowed"),
    "sportsshoes":     dict(strategy="sitemap_jsonld", crawl_delay_s=2.0, robots_status="allowed",
                            notes="Disallow:/ applies only to Applebot-Extended, not to *."),
    "deporvillage":    dict(strategy="headless", crawl_delay_s=6.0, robots_status="blocked_403",
                            notes="Returns 403 on robots.txt itself. Headless per client decision; keep volume minimal."),
    "sprinter":        dict(strategy="headless", crawl_delay_s=6.0, robots_status="blocked_403",
                            notes="Returns 403 on robots.txt itself. Headless per client decision; keep volume minimal."),
    # robots.txt is readable and permissive, but every other path sits behind a
    # Cloudflare interstitial. Headless clears it for ordinary HTML pages, yet
    # the gzipped sitemaps still return 403 and the catalogue is JS-rendered, so
    # product discovery needs a bespoke path rather than the sitemap walker.
    "ekosport":        dict(strategy="headless", crawl_delay_s=6.0,
                            robots_status="cloudflare_challenge",
                            sitemap_url="https://www.ekosport.es/sitemap_es.xml",
                            notes="robots.txt allows crawling; Cloudflare challenges everything else. "
                                  "Headless passes for HTML, but sitemap_*.xml.gz stays 403 and product "
                                  "links are JS-rendered. Needs a custom discovery module before enabling."),
    "i-run":           dict(strategy="headless", crawl_delay_s=6.0, robots_status="blocked_403",
                            notes="Returns 403 on robots.txt itself. Headless per client decision; keep volume minimal."),
}


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", "", s)                 # drop "(incl. Runnerinn, ...)"
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def main() -> int:
    ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)["Listado"]
    it = ws.iter_rows(values_only=True)
    next(it)

    rows = []
    for r in it:
        if not r or not r[0]:
            continue
        name = str(r[0]).strip()
        url = re.sub(r"\s*\[[^\]]*\]", "", str(r[3] or "")).strip().rstrip(",").strip()
        s = slug(name)
        pol = POLICY.get(s, dict(strategy="sitemap_jsonld", crawl_delay_s=3.0,
                                 robots_status="unknown",
                                 notes="Policy not yet checked; stays disabled."))
        # PostgREST rejects a batch whose objects have differing key sets
        # ("All object keys must match"), so every row carries every column.
        rows.append({"slug": s, "name": name, "classification": str(r[2]).strip(),
                     "base_url": url, "records_ref": int(r[1]), "enabled": False,
                     "strategy": pol["strategy"], "crawl_delay_s": pol["crawl_delay_s"],
                     "robots_status": pol["robots_status"],
                     "sitemap_url": pol.get("sitemap_url"),
                     "notes": pol.get("notes")})

    sb = Supabase()
    sb.upsert("competitors", rows, on_conflict="slug")

    checked = sum(1 for r in rows if r["robots_status"] != "unknown")
    print(f"seeded {len(rows)} competitors · {checked} with a verified crawl policy")
    for r in rows:
        if r["robots_status"] != "unknown":
            print(f"  {r['slug']:18} {r['strategy']:15} delay {r['crawl_delay_s']}s  {r['robots_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
