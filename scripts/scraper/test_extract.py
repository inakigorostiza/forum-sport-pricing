#!/usr/bin/env python3
"""Offline tests for the extractor. No network: runs against a saved page."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from scraper.extract import extract, gtin13, price

fails = []
def eq(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:46} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r}, want {want!r}")

print("── gtin13 normalisation ──")
eq("12-digit UPC is left-padded", gtin13("195394930146"), "0195394930146")
eq("13-digit EAN unchanged",      gtin13("4550457739184"), "4550457739184")
eq("14-digit GTIN trimmed",       gtin13("04550457739184"), "4550457739184")
eq("int input",                   gtin13(195394930146), "0195394930146")
eq("punctuation stripped",        gtin13("4550-4577-39184"), "4550457739184")
eq("garbage -> None",             gtin13("n/a"), None)
eq("None -> None",                gtin13(None), None)

print("── price parsing ──")
eq("float",              price(112.5), 112.5)
eq("es-ES decimal comma", price("112,50"), 112.5)
eq("thousands + decimal", price("1.234,56 €"), 1234.56)
eq("en-US thousands",     price("1,234.56"), 1234.56)
eq("currency prefix",     price("€112.50"), 112.5)
eq("bare string",         price("112.5"), 112.5)
eq("empty -> None",       price(""), None)

print("── real page: ASICS Novablast 4 Paris (atmosferasport.es) ──")
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "atmosfera_novablast4.html"
if not FIXTURE.exists():
    print(f"  SKIP  fixture missing: {FIXTURE}")
    print("\nFAILURES:", fails if fails else "none")
    sys.exit(1 if fails else 0)
html = FIXTURE.read_text(errors='ignore')
r = extract(html, "https://www.atmosferasport.es/asics/zapatillas-de-running-asics-novablast-4-paris-hombre-verde-99173.html")
p, offers = r["product"], r["offers"]
eq("ext_id",     p["ext_id"], "99173")
eq("brand_raw",  p["brand_raw"], "Asics")
eq("offers found", len(offers), 1)
o = offers[0]
eq("gtin13",       o["gtin13"], "4550457739184")
eq("mpn",          o["mpn"], "1011B955-750")
eq("price",        o["price"], 112.5)
eq("currency",     o["currency"], "EUR")
eq("size_raw",     o["size_raw"], "47")
eq("availability", o["availability"], "https://schema.org/InStock")
print(f"  title: {p['title']}")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
