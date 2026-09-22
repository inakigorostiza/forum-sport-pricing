# Competitor price monitoring

How the price-scraping agent works, what it crawls, and how to add a site.

## What it does

1. **discover** (weekly) — walk a competitor's sitemap, filter to URLs that could
   be a men's running/trail shoe of a brand we stock, fetch each one, extract
   offers from its structured data, and record which pages matched our catalogue.
2. **refresh** (daily) — re-fetch only the pages already known to match. Two
   orders of magnitude cheaper than a full pass.

```bash
python3 scripts/scraper/run.py --competitor atmosfera-sport --phase discover --limit 300
python3 scripts/scraper/run.py --competitor atmosfera-sport --phase refresh --no-cache
python3 scripts/scraper/test_extract.py          # offline, no network
```

## How products are matched

**The EAN is the join key.** 24.108 of our 24.109 SKUs carry a globally
resolvable GS1 code, and competitors publish `gtin13` in their schema.org data,
so matching is exact — no fuzzy name comparison.

The trap that makes or breaks it: **50,7 % of our EANs are stored as 12-digit
UPCs**. Competitors publish 13 digits. Both sides are normalised to GTIN-13
(`skus.gtin13` is a generated column; `scraper/extract.py:gtin13()` does the
same for scraped values). In the first real crawl, **20 of 26 matched models
came through 12-digit EANs** — without the padding we would have found 6.

## Politeness

Enforced in `scraper/fetch.py`, not left to each site module:

- one request at a time per host, never faster than the configured `crawl_delay_s`
- `robots.txt` honoured where readable, via `urllib.robotparser`
- an identifiable User-Agent on sites that permit crawling, so they can block us
  by name if they prefer
- every run writes to `crawl_log` with the **smallest gap actually observed**,
  so politeness is provable after the fact, not merely claimed
- fetch failures are recorded, never swallowed — a silent error is
  indistinguishable from "this page had no offers"

## Crawl policy per site

Established by fetching each `robots.txt` on 2026-09-22, not assumed:

| Competitor | Policy | Strategy | Delay |
|---|---|---|--:|
| Atmósfera Sport | allowed | `sitemap_jsonld` | 2 s |
| Tradeinn | allowed (`Disallow: /` applies only to EtaoSpider) | `sitemap_jsonld` | 2 s |
| Decathlon | allowed, publishes `Crawl-delay: 2–5` | `sitemap_jsonld` | 5 s |
| SportsShoes | allowed (`Disallow: /` applies only to Applebot-Extended) | `sitemap_jsonld` | 2 s |
| Running Emotion | allowed | `sitemap_jsonld` | 2 s |
| Deporvillage, Sprinter, i-Run | **403 on `robots.txt` itself** | `headless` | 6 s |

The last three actively refuse automated access. Reaching them means presenting
as a browser, which is a commercial/ToS decision for Forum Sport and LIN3S —
taken deliberately, not by default. They remain `enabled = false` in the
`competitors` table until switched on explicitly, and the code never touches a
login, cart or account page.

Everything else in `competitors` is `robots_status = 'unknown'` and disabled:
a site is crawled only after its policy has been read.

## Data model

| Table | |
|---|---|
| `competitors` | crawl policy; `enabled` is opt-in |
| `competitor_products` | one discovered page; `is_relevant` marks the refresh set |
| `competitor_offers` | **append-only** price history, one row per observation |
| `crawl_log` | every run, with pages fetched and the minimum observed gap |

`competitor_offers` is never updated in place. "Current price" is
`v_precio_actual_competencia` (a `distinct on`), so a repricing decision can
always be traced back to the observation and the raw payload behind it.

### Views

- `v_precio_actual_competencia` — latest observation per size per competitor
- `v_comparativa_precios` — our price beside theirs, per model per competitor
- `v_posicion_precio` — cheapest rival, gap, and **`margen_si_igualamos`**: the
  margin that would survive matching them. This is what the pricing calculator reads.
- `v_cobertura_competencia` — how much of our catalogue each rival carries

**These are private.** Unlike the catalogue, they carry no `anon` grant: the
individual prices are public on the rivals' own sites, but this assembled view
of them is Forum Sport's commercial analysis. Only the `service_role` key reads
them. Verified: `anon` gets `401` on all four.

### The one public surface

`comparativa_publica` is a **table**, refreshed by `refresh_comparativa_publica()`
at the end of every crawl, and it is the only thing the landing page reads. It
carries the two prices and the difference between them — what a shopper could
work out by opening both websites — and deliberately **no margin, cost, coverage
or `margen_si_igualamos`**.

It is a table rather than a view on purpose: a view over the private tables would
need `SECURITY DEFINER` to bypass their RLS, which Supabase's linter flags as an
ERROR, and rightly — it is a standing hole that reads whatever the definition
happens to select. A table needs no privilege escalation: `service_role` writes
it, `anon` reads it under an ordinary policy, and the column list is fixed at
write time. It also makes the page cheaper: one small read instead of a join
across the whole offer history.

Verified: `anon` reads `comparativa_publica` (200) but gets `401` on every
private table, every strategy view, and on the refresh function itself.

## Adding a competitor

1. Check its `robots.txt` by hand and record the finding in
   `scripts/seed_competitors.py:POLICY`.
2. Re-run `python3 scripts/seed_competitors.py`.
3. Fetch one product page and confirm the extractor handles it — add a fixture
   under `scraper/fixtures/` and a case to `test_extract.py`.
4. Only then set `enabled = true`.

`scraper/extract.py` already handles both shapes seen in the wild: a
`ProductGroup` with `hasVariant` per size, and a plain `Product`. A site with no
structured data needs a small module under `scraper/sites/`.

## Costs

A full Atmósfera sitemap pass is ~31.000 URLs; at 2 s that is ~17 hours, against
a GitHub Actions allowance of 2.000 minutes/month on a private repo. Hence the
two phases: discovery narrows 31.789 sitemap URLs to ~2.000 candidates, and the
daily refresh then touches only the few hundred that actually matched.

Measured on the first real run: discover 200 pages in 6,7 min; refresh 26 pages
in 0,8 min.
