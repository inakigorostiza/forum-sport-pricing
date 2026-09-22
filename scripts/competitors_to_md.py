#!/usr/bin/env python3
"""Generate competitors.md from dataset/Competidores_PricingDinamico.xlsx.

Kept as a script rather than a hand-written file so the document can be
regenerated when the source list changes, and so the cleaning rules are
visible instead of applied silently by hand.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "dataset" / "Competidores_PricingDinamico.xlsx"
OUT = ROOT / "competitors.md"

# Categories are listed largest-first; the prose draws the distinction that
# actually matters (comparador vs retailer vs the brand itself).

# Brands Forum Sport sells that also appear here as direct sellers. Counts come
# from the live database (v_por_marca); frozen here so the script has no
# network dependency.
D2C = {
    "nike": (239, "143,82 €"), "adidas": (231, "128,87 €"),
    "salomon": (153, "150,33 €"), "puma": (106, "99,21 €"),
    "thenorthface": (20, "145,00 €"), "hellyhansen": (19, "149,47 €"),
    "underarmour": (7, "136,71 €"),
}
CATALOGUE_MODELS = 1483


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum())


def es(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def read() -> list[dict]:
    if not XLSX.exists():
        sys.exit(f"Not found: {XLSX}")
    rows = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)["Listado"]
    it = rows.iter_rows(values_only=True)
    next(it)
    out = []
    for r in it:
        if not r or not r[0]:
            continue
        # The URL column carries citation artifacts like "[tradeinn.com]".
        url = re.sub(r"\s*\[[^\]]*\]", "", str(r[3] or "")).strip().rstrip(",").strip()
        out.append({"name": str(r[0]).strip(), "records": int(r[1]),
                    "cls": str(r[2]).strip(), "url": url})
    return sorted(out, key=lambda x: -x["records"])


def main() -> int:
    rows = read()
    total = sum(r["records"] for r in rows)
    share = lambda n: f"{n / total * 100:.1f} %".replace(".", ",")

    cats: dict[str, list[dict]] = {}
    for r in rows:
        cats.setdefault(r["cls"], []).append(r)
    cat_keys = sorted(cats, key=lambda c: -sum(x["records"] for x in cats[c]))

    def topn(n: int) -> str:
        return share(sum(r["records"] for r in rows[:n]))

    L: list[str] = []
    add = L.append

    add("# Competitive landscape")
    add("")
    add("Sellers competing with Forum Sport on the running and trail catalogue.")
    add("Generated from `dataset/Competidores_PricingDinamico.xlsx` by")
    add("`scripts/competitors_to_md.py` — regenerate rather than edit by hand.")
    add("")
    add(f"**{len(rows)} sellers · {es(total)} records.**")
    add("")
    add("> **What \"records\" counts is not defined in the source file.** It behaves")
    add("> like matched product listings or offers observed, not revenue and not")
    add("> visits. Treat it as relative presence, not market share.")
    add("")

    add("## The market is top-heavy")
    add("")
    add("| | Share of records |")
    add("|---|---|")
    for n in (1, 3, 5, 10):
        add(f"| Top {n} | {topn(n)} |")
    add("")
    add(f"The top 5 sellers carry **{topn(5)}** of all records and the top 10")
    add(f"**{topn(10)}**, so {len(rows) - 10} of the {len(rows)} names are a long tail. Monitoring that")
    add("covers the top 10 covers most of the visible market.")
    add("")

    add("## By type of seller")
    add("")
    add("| Type | Sellers | Records | Share |")
    add("|---|--:|--:|--:|")
    for c in cat_keys:
        g = cats[c]
        rec = sum(x["records"] for x in g)
        add(f"| {c} | {len(g)} | {es(rec)} | {share(rec)} |")
    add("")
    add("Two of these behave differently from the rest and are worth separating")
    add("before any pricing rule is written:")
    add("")
    add("- **Google Shopping is a comparador, not a retailer.** It is the single")
    add("  largest line at 31 %, but it resells nothing — it is the surface where")
    add("  the others' prices are compared. Counting it as a competitor double-counts")
    add("  the sellers listed inside it. It is a *channel to monitor*, not a rival.")
    add("- **Tradeinn is an aggregate** of Runnerinn, Dressinn and Trekkinn, so its")
    add("  single line represents several storefronts.")
    add("")

    add("## Brands that are also competitors")
    add("")
    add("Every seller classified `Marca` sells a brand Forum Sport stocks — they")
    add("compete directly with their own retailer.")
    add("")
    add("| Brand | D2C records | Models in catalogue | Average PVP |")
    add("|---|--:|--:|--:|")
    covered = 0
    for r in rows:
        if r["cls"] != "Marca":
            continue
        hit = D2C.get(slug(r["name"]))
        if hit:
            covered += hit[0]
            add(f"| {r['name']} | {es(r['records'])} | {hit[0]} | {hit[1]} |")
        else:
            add(f"| {r['name']} | {es(r['records'])} | — | — |")
    add("")
    pct = f"{covered / CATALOGUE_MODELS * 100:.1f}".replace(".", ",")
    add(f"Those brands account for **{es(covered)} of {es(CATALOGUE_MODELS)} models "
        f"({pct} %)** of the catalogue.")
    add("Their direct presence is small in records (0,5 % of the total) but it sets")
    add("the reference price for more than half of what Forum Sport sells: a brand's")
    add("own site is the price customers treat as official.")
    add("")

    add("## All sellers")
    add("")
    add("| # | Seller | Type | Records | Share | Site |")
    add("|--:|---|---|--:|--:|---|")
    for i, r in enumerate(rows, 1):
        host = re.sub(r"^https?://(www\.)?", "", r["url"]).rstrip("/")
        link = f"[{host}]({r['url']})" if r["url"] else "—"
        add(f"| {i} | {r['name']} | {r['cls']} | {es(r['records'])} | {share(r['records'])} | {link} |")
    add("")

    add("## Notes on the source")
    add("")
    add("- URLs in the spreadsheet carried citation artifacts (`[tradeinn.com]`,")
    add("  a duplicated `[runningemotion.com]`); the generator strips them.")
    add("- Category labels are kept verbatim from the source, in Spanish.")
    add("- Several sellers are not Spanish storefronts (`nencinisport.it`,")
    add("  `sportsshoes.com`, `bike24.es`, `runningwarehouse.eu`), so shipping cost")
    add("  and delivery time sit between their listed price and the customer's real")
    add("  cost. A price-match rule that ignores that will chase prices that were")
    add("  never truly comparable.")
    add("")

    add("## Why this matters for dynamic pricing")
    add("")
    add("The catalogue analysis found the problem; this list constrains the fix.")
    add("**60,2 % of the lowest-stock tier is already discounted against a 55,6 %")
    add("catalogue average** — Forum Sport is discounting what it barely has.")
    add("Before a rule reprices against a rival, it needs to know:")
    add("")
    add(f"1. **Which sellers count.** The top 10 cover {topn(10)} of records;")
    add("   the tail mostly adds noise.")
    add("2. **Whether the rival is comparable.** A comparador, a cross-border seller")
    add("   and the brand's own site are three different kinds of reference price.")
    add("3. **Whether matching is worth it.** Margin is banded at 15/20/30/40 %, so on")
    add("   a *muy bajo* margin model there is very little room to follow a rival down.")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(rows)} sellers, {es(total)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
