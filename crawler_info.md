# Crawler info — a per-competitor guide

How each competitor is crawled, why that way, and what it takes to repeat it.
Written so that someone else — or this same project in six months, once a site
has changed — can reproduce or repair a crawl without researching it again.

Access policies and politeness rules live in [SCRAPING.md](SCRAPING.md); the
build narrative is in [activities.md](activities.md).

---

## The procedure: five questions

Every site is assessed with the same five questions, in this order. It is
automated in `scripts/scraper/evaluate.py`, which writes `data/evaluation.json`.

```bash
python3 scripts/scraper/evaluate.py                    # every unevaluated site
python3 scripts/scraper/evaluate.py --only wala,base   # named sites
python3 scripts/scraper/evaluate.py --no-browser       # skip the patchright retry
```

| # | Question | How it is answered | Verdict if it fails |
|---|---|---|---|
| 1 | Does `robots.txt` come back to an HTTP client? | GET with a browser User-Agent | retry with patchright, else `BLOCKED` |
| 2 | Does it declare a readable sitemap? | `Sitemap:` lines in robots.txt | `NO SITEMAP` / `SITEMAP UNREADABLE` |
| 3 | Are there URLs that look like running shoes? | keyword filter on the slug | `NO SHOE URLS` |
| 4 | Does a product page carry structured data? | `extract.py` over 6 pages | `NO STRUCTURED DATA` |
| 5 | Does anything match our catalogue? | `gtin13` ∈ our EANs, or `mpn` base ∈ `ref_prov` | `NO MATCH KEY` / `no matches in sample` |

**The order matters.** Each step costs more than the last, so a site that fails
at step 1 never triggers a 24 MB sitemap download.

**Never judge a site on a small sample.** See the lessons below: two sites I
declared dead on 5 pages are now the second and fifth largest data sources.

---

## The two matching keys

Everything depends on being able to say *this product of theirs is this product
of ours*. There are exactly two ways, and they must not be confused.

### EAN / GTIN-13 — exact, at size level

The preferred key. 24.108 of our 24.109 SKUs carry a resolvable GS1 code, and
most shops publish `gtin13` in their JSON-LD.

**The trap that breaks everything silently:** 50,7 % of our EANs are stored as
12-digit UPCs and the rest as 13-digit EANs, while competitors publish 13. A
direct join would drop half the catalogue without raising a single error. Both
sides are normalised to 13 digits — `skus.gtin13` is a generated column, and
`extract.py:gtin13()` does the same to scraped values.

> In the first real crawl, **20 of 26 matched models came through 12-digit
> EANs**. Without the padding it would have been 6.

### Article code — model level

For brands that publish no GTIN (adidas, Nike). The manufacturer code —
`GW4139`, `HV8116` — is what our catalogue stores as `models.ref_prov`.

- **adidas:** the code is the last path segment of the URL
  (`/zapatilla-galaxy-6/GW4139.html`), so the crawl set can be narrowed to our
  catalogue *before* fetching anything — 66 pages instead of 15.337.
- **Nike:** the URL carries no code (opaque slugs). The JSON-LD `mpn` is
  `style-colour` (`HV8116-001`), split at the dash. One Nike page lists every
  colourway of a style, so a single fetch can match several of our models.

`v_ofertas_emparejadas` records `match_method` on every offer, so a model-level
article-code match is never silently conflated with a size-exact GTIN match.

---

## The two fetchers

### Plain HTTP — `scraper/fetch.py`

The default, and what most sites need. One request at a time per host, never
faster than `crawl_delay_s`, `robots.txt` honoured, an identifiable User-Agent,
and every failure recorded — never swallowed, because a silent error is
indistinguishable from "this page had no offers".

### Patchright — `scraper/sites/adidas.py`

Only where it is required. Ordinary Playwright **is detected**; patchright
launched as a persistent context with no automation flags is not.

```bash
pip install patchright && python3 -m patchright install chromium
```

Tested against adidas: plain HTTP, real headless Chrome, and Chrome with
puppeteer's stealth plugin **all receive 403**; patchright passes.

> `timeout` is in **seconds** in both fetchers. Playwright natively wants
> milliseconds, and keeping its unit here made `discover.sitemap_urls` — which
> passes `timeout=60` — time out after 60 ms and report every sitemap as
> unreachable. That single unit mismatch produced 28 wrong verdicts.

---

## Per-competitor configuration

Everything that differs per shop lives in the `competitors` table, so adding a
site is configuration rather than code:

| Column | Purpose |
|---|---|
| `sitemap_url` | the sitemap **robots.txt actually declares** — never a guess |
| `product_url_re` | regex a URL must match to be a product page |
| `crawl_delay_s` | minimum gap between requests; honours published `Crawl-delay` |
| `strategy` | `sitemap_jsonld` (plain HTTP) or `headless` (patchright) |
| `enabled` | opt-in; a site is never crawled until deliberately switched on |

URL shapes differ more than expected, which is why `product_url_re` exists:

| Shop | Product URL shape | Pattern |
|---|---|---|
| Atmósfera Sport | `/brand/slug-99173.html` | `-\d{3,}\.html?$` |
| Tradeinn | `/runnerinn/es/slug/143155557/p` | `/\d+/p$` |
| Top4Running, 11teamsports | `/p/slug` | `/p/` |
| Bergfreunde | `/slug/` | `^https://www\.bergfreunde\.es/[^/]+/$` |
| i-Run | `/…/Trailtalon-Speed_fiche_143095.html` | `_fiche_\d+\.html$` |
| Viladomat | `/es/product/slug` | `/product/` |

Without it the crawler either burns requests on category pages (Atmósfera) or
rejects everything (`/p/`, trailing slash).

---

## Adding a competitor

1. `python3 scripts/scraper/evaluate.py --only <slug>` and read the verdict.
2. Record the policy in `scripts/seed_competitors.py:POLICY`, then re-seed.
3. Configure `sitemap_url`, `product_url_re`, `crawl_delay_s`, `strategy`.
4. Save a page under `scraper/fixtures/` and add a case to `test_extract.py`,
   so the extractor is covered without touching the network.
5. `--limit 8 --dry-run`, inspect, and only then set `enabled = true`.
6. First real crawl at `--limit 300`, and measure the match rate.

---

## Lessons that cost time

**A 5-page sample proves nothing.** I wrote off Bergfreunde and Top4Running on
5 pages with 0 matches. At 300 pages they are the second and fifth largest
sources (1.120 and 769 offers). **Use at least 100 pages before concluding
anything.** Viladomat is genuinely dead — 0 from 300.

**"No structured data" was my own bug.** `_ld_nodes` only flattened `@graph`, so
a `Product` nested inside `WebPage.mainEntity` was invisible. That is exactly how
Tradeinn publishes — the largest competitor on the list — which went from "no
data" to 9 offers with 9 GTINs the moment it was fixed. It now also descends
through `mainEntity`, `mainEntityOfPage`, `itemListElement` and `item`.

**A fallback that can overwrite a better answer is worse than no fallback.**
The patchright retry replaced successful HTTP results with its own failures:
Wala went from 102.493 URLs to "sitemap unreadable". The retry is now only
accepted when it moves *up* the verdict ranking.

**One `curl` to a homepage is not an access test.** I reported i-Run,
Deporvillage and Sprinter as "403 blocked". None of them are: i-Run is fully
crawlable and already matching, Deporvillage serves 129.330 sitemap URLs and
Sprinter 46.187, both with real prices.

**A readable `robots.txt` does not mean an accessible site.** Decathlon
publishes a permissive `robots.txt` with `Crawl-delay` and returns 403 on its
homepage. Declared policy and what the WAF allows are different things.

**Source-list volume predicts nothing.** Atmósfera has 10.461 records and yields
26 models; Bergfreunde has 1.808 and yields 73.

---

## Evaluation results

Measured 2026-09-22 by `scripts/scraper/evaluate.py`. "Offers", "GTIN" and
"Matched" come from a sample of up to 6 product pages, so a zero there means
*not found in the sample*, not *impossible*.
| Competitor | Verdict | Sitemap URLs | Shoe candidates | Offers | GTIN | MPN | Matched |
|---|---|--:|--:|--:|--:|--:|--:|
| i-Run | VIABLE · matches found | 9.500 | 678 | 31 | 31 | 0 | 11 |
| Alltricks | VIABLE · no matches in sample | 5.420 | 4 | 4 | 4 | 4 | 0 |
| Nencini Sport | VIABLE · no matches in sample | 7.973 | 56 | 6 | 0 | 6 | 0 |
| The North Face | VIABLE · no matches in sample | 4.034 | 41 | 41 | 31 | 3 | 0 |
| 11teamsports | VIABLE · no matches in sample | 26.904 | 187 | 87 | 87 | 0 | 0 |
| Deporvillage | NO MATCH KEY | 129.330 | 386 | 80 | 0 | 0 | 0 |
| Sprinter | NO MATCH KEY | 46.187 | 356 | 92 | 0 | 0 | 0 |
| Decathlon | NO MATCH KEY | 86.943 | 312 | 6 | 0 | 0 | 0 |
| JD Sports | NO MATCH KEY | 17.680 | 246 | 6 | 0 | 0 | 0 |
| Barrabés | NO MATCH KEY | 30.586 | 94 | 6 | 0 | 0 | 0 |
| El Corte Inglés | NO STRUCTURED DATA | 12.020 | 16 | 0 | 0 | 0 | 0 |
| RunningXpert | NO STRUCTURED DATA | 11.902 | 317 | 0 | 0 | 0 | 0 |
| Wala | NO STRUCTURED DATA | 102.493 | 63 | 0 | 0 | 0 | 0 |
| Foot Locker | NO STRUCTURED DATA | 2.896 | 133 | 0 | 0 | 0 | 0 |
| Running Warehouse | NO STRUCTURED DATA | 466 | 3 | 0 | 0 | 0 | 0 |
| Under Armour | NO STRUCTURED DATA | 6.063 | 10 | 0 | 0 | 0 | 0 |
| Décimas | NO STRUCTURED DATA | 13.204 | 155 | 0 | 0 | 0 | 0 |
| SportsShoes | NO SITEMAP | 0 | 0 | 0 | 0 | 0 | 0 |
| Running Emotion | NO SITEMAP | 0 | 0 | 0 | 0 | 0 | 0 |
| Fútbol Emotion | NO SITEMAP | 0 | 0 | 0 | 0 | 0 | 0 |
| Salomon | NO SITEMAP | 0 | 0 | 0 | 0 | 0 | 0 |
| Basketball Emotion | NO SITEMAP | 0 | 0 | 0 | 0 | 0 | 0 |
| Ekosport | SITEMAP UNREADABLE | 0 | 0 | 0 | 0 | 0 | 0 |
| Bike24 | SITEMAP UNREADABLE | 0 | 0 | 0 | 0 | 0 | 0 |
| Base | NO SHOE URLS | 6 | 0 | 0 | 0 | 0 | 0 |
| Tennis Point | NO SHOE URLS | 7 | 0 | 0 | 0 | 0 | 0 |
| Helly Hansen | BLOCKED | 0 | 0 | 0 | 0 | 0 | 0 |
| Puma | BLOCKED | 0 | 0 | 0 | 0 | 0 | 0 |
### What the verdicts mean, and what to do next

| Verdict | Meaning | Next step |
|---|---|---|
| **VIABLE · matches found** | Works end to end today | Configure and crawl |
| **VIABLE · no matches in sample** | Publishes a match key; catalogue may not overlap | Crawl 300 pages before judging |
| **NO MATCH KEY** | Prices, but no `gtin13` and no `mpn` | Check whether the EAN sits in a spec table outside the JSON-LD |
| **NO STRUCTURED DATA** | No usable JSON-LD; likely client-rendered | Retry with patchright; then a per-site CSS parser |
| **NO SITEMAP** | `robots.txt` declares none | Discovery via category pages |
| **SITEMAP UNREADABLE** | Sitemap declared but refused | Usually a WAF; patchright |
| **NO SHOE URLS** | Sitemap has only a handful of URLs | Nothing to do — not a real catalogue feed |
| **BLOCKED** | `robots.txt` itself refused, browser included | Affiliate feed or a data provider |

The dominant obstacle is **not access — it is missing identifiers**. Five large
retailers (Deporvillage, Sprinter, Decathlon, JD Sports, Barrabés) serve big
sitemaps and real prices but publish neither `gtin13` nor `mpn`, so there is
nothing to join on. Solving that one problem would unlock more coverage than any
amount of additional bot evasion.
