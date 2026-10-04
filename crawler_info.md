# Crawler info — a per-competitor guide

How each competitor is crawled, why that way, and what it takes to repeat it.
Written so that someone else — or this same project in six months, once a site
has changed — can reproduce or repair a crawl without researching it again.

Access policies and politeness rules live in [SCRAPING.md](SCRAPING.md); the
build narrative is in [activities.md](activities.md).

---

## Where the data stands (2026-10-04)

**16 competitors live · 571 of 1.483 models covered (38,5 %) · 1.054
model-competitor pairs.** On average we are **+10,3 %** above the competition and
cheaper on **30,7 %** of comparisons.

> Those two figures read +7,4 % and 34,6 % until migration 020. They moved
> because the comparison had been picking an arbitrary price whenever several
> offers from one seller matched the same model — see "a tie in the dedupe key"
> under *Lessons that cost time*. The new numbers are worse, and correct.

| Competitor | Models | Avg. Δ vs us | Matching key |
|---|--:|--:|---|
| Running Emotion | 283 | +14,3 % | ref_prov |
| Fútbol Emotion | 182 | +10,2 % | ref_prov |
| Nike | 93 | +16,0 % | ref_prov |
| Bergfreunde | 73 | +10,8 % | gtin13 |
| adidas | 66 | −5,9 % | ref_prov |
| i-Run | 63 | +10,2 % | gtin13 |
| Basketball Emotion | 53 | +11,2 % | ref_prov |
| Tradeinn | 52 | +21,2 % | gtin13 |
| El Corte Inglés | 47 | +1,0 % | gtin13 |
| Top4Running | 42 | +12,6 % | gtin13 |
| Salomon | 27 | −0,8 % | ref_prov |
| Atmósfera Sport | 26 | +7,2 % | gtin13 |
| Décimas | 20 | −7,1 % | gtin13 |
| Viladomat | 14 | +15,3 % | gtin13 |
| JD Sports | 10 | −6,6 % | gtin13 |
| The North Face | 3 | 0,0 % | gtin13 |

The four sellers we undercut — adidas, Décimas, JD Sports, Salomon — are two
brand stores and two discounters. Against every specialist retailer we are the
more expensive option.

### The 14 sellers re-examined on 2026-09-23

| Seller | Outcome | What was actually wrong |
|---|---|---|
| Running Emotion | ✅ 283 models | sitemap recursion stopped at non-`.xml` children |
| Fútbol Emotion | ✅ 182 models | same, plus its own domain name tripped the EXCLUDE filter |
| Basketball Emotion | ✅ 53 models | same; also needed the article-code base match |
| Décimas | ✅ 20 models | CDATA wrapper broke `json.loads` on a payload full of EANs |
| Viladomat | ✅ 14 models | `--limit` sampled the head of a brand-grouped sitemap |
| The North Face | ✅ 3 models | global sitemap never reached `/es-es/`; 403s the honest UA |
| Under Armour | ⚠️ key, no overlap | publishes gtin13; we stock only 7 UA models |
| Wala | ❌ discovery | 51.246 sitemap URLs, all categories, zero products |
| RunningXpert | ❌ discovery | 11.902 URLs, only 32 products |
| Running Warehouse | ❌ discovery | 466-URL sitemap, 2 shoe entries |
| Foot Locker | ❌ no key | 2.200 product pages, no GTIN and no article code |
| Nencini Sport | ❌ blocked | 403 on every product page |
| 11teamsports | ❌ blocked | declares a sitemap that 403s |
| Alltricks | ❌ blocked | 403 on `robots.txt` itself |

Six of the fourteen now feed the landing page. **Every one of those six failed
for a reason inside this crawler, not inside the shop** — and none of them was
the reason first recorded.

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
| `sitemap_max_children` | child-sitemap fan-out limit; NULL uses the default of 12 |
| `user_agent` | `honest` (default) or `browser`, for shops that 403 every other client |

URL shapes differ more than expected, which is why `product_url_re` exists:

| Shop | Product URL shape | Pattern |
|---|---|---|
| Atmósfera Sport | `/brand/slug-99173.html` | `-\d{3,}\.html?$` |
| Tradeinn | `/runnerinn/es/slug/143155557/p` | `/\d+/p$` |
| Top4Running, 11teamsports | `/p/slug` | `/p/` |
| Bergfreunde | `/slug/` | `^https://www\.bergfreunde\.es/[^/]+/$` |
| i-Run | `/…/Trailtalon-Speed_fiche_143095.html` | `_fiche_\d+\.html$` |
| Viladomat | `/es/product/brand_slug_id` | `/es/product/` (Spanish store only) |
| Running / Fútbol / Basketball Emotion | `/es/comprar/zapatilla/brand/slug` | `/comprar/zapatilla/` |
| Décimas | `/es-es/slug-pum8240000.html` | `-[a-zA-Z]{3}\d{6,}\.html$` |
| The North Face | `/es-es/p/calzado-747784/slug-NF0A8A96` | `/es-es/p/` |

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
anything.**

**Where you sample matters as much as how much.** I then declared Viladomat
"genuinely dead — 0 from 300". It was not. `--limit` takes the *head* of the
candidate list, a sitemap is usually grouped by brand, and those first 300 URLs
were brands we do not stock. Sampling the same site with a stride across the
whole list returned 16 matches in 10 pages, and the full crawl returned 170
offers. **Sample with a stride, never from the head.**

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

**A shoe-shaped URL is not a product page.** My re-probe of 14 sellers fetched
the first six URLs matching `/zapatilla|shoe|calzado/` and reported "no
structured data" for five of them. Every URL it tested was a *category listing*
— `/mens-running-shoes.html`, `/es-es/zapatillas-running-hombre`,
`/category/zapatillas/adidas/astir.html` — because sitemaps list categories
before products. The sites were fine; the sample was not.

**A hostname is not a path.** `is_candidate()` slugged the whole URL, so
`futbolemotion.com` was rejected by its own domain for containing the EXCLUDE
word "futbol", and every URL on `top4running.es` passed the shoe test because
the *domain* contains "running" — 6.186 candidates of which 5.441 were jackets,
joggers and neck gaiters. Judge the path, not the host.

**A child sitemap is not always named `.xml`.** The Emotion shops paginate
theirs as `/es/sitemap/productos/limit/1000/offset/0/idioma/es`. The walker
recursed only into locs ending in `.xml`, so it returned those index pages as
if they were products: a 2.754-URL catalogue looked like 75 junk entries. Their
sitemap is also three levels deep — root → `/es/sitemap.xml` → paginated
children — and the default fan-out cap of 12 silently truncated Fútbol Emotion
to a third of its catalogue, which is why `sitemap_max_children` now exists.

**`json.loads` is not a parser for the wild.** Décimas publishes every size's
EAN in `<script id="zandman-data" type="application/json"><![CDATA[…]]>`. The
CDATA wrapper made `json.loads` reject 1,3 MB of perfectly good state, and the
page reported "no offers". `extract_state()` now strips the wrapper and uses
`raw_decode`, which reads the leading value and ignores trailing junk.

**Diagnose before concluding — and separate the causes.** The probe swallowed
failed fetches with `if not html: continue`, so "blocked" and "publishes no
data" produced the identical verdict. Nine of ten "dead" sites turned out to
have failed at *discovery*; only Nencini was genuinely blocked. Every wrong
verdict in this project has come from the same place: the crawler's own
shortcomings, reported as facts about the seller.

**A tie in the dedupe key is a decision made by coin flip.** The comparison
collapsed offers with `distinct on (modelo, competidor, coalesce(gtin13,
size_raw, ''))`. Offers matched by article code carry no `gtin13` and usually no
`size_raw`, so for every one of them that key was the same empty string:
`DISTINCT ON` kept one arbitrary row and threw the rest away *before* `min()`
could see them. 290 of 1.054 pairs — 27,5 % — were showing a competitor price
picked at random from candidates differing by 24,49 € on average. `DISTINCT ON`
always returns a row; whether it is the right one depends on the `ORDER BY`
breaking the tie. When it does not, there is no error and no warning, just a
plausible number. Fixed in migration 020 by making keyless offers
un-collapsible, which also makes the view obey the rule the project already
documented: the reference price is the cheapest found.

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
### Re-test with a browser (2026-09-23)

`NO STRUCTURED DATA` means *we could not read it*, not *it is not there* — the
Tradeinn case proved that. So all seven were re-tested with patchright against
real product pages. One was rescued:

| Site | Rendered result | Conclusion |
|---|---|---|
| **Under Armour** | **60 offers, 60 gtin13, 60 mpn** | verdict was wrong — it is client-rendered |
| Wala | 11 offers, 0 gtin, 0 mpn | reclassify as NO MATCH KEY |
| RunningXpert | 0 offers | not a rendering problem |
| Foot Locker | 0 offers | not a rendering problem |
| Décimas | 0 offers | not a rendering problem |
| Running Warehouse | 0 offers | not a rendering problem |
| El Corte Inglés | sitemap unreadable | never got that far |

Under Armour was then crawled in full: 45 candidate pages, **954 offers
extracted, 0 matched**. Their Spanish store lists training shoes, not the seven
UA running models we stock. Disabled — the crawl works, the catalogue does not
overlap.

> **Lesson.** "It renders" and "it is useful" are different results. Rendering
> fixed the extraction for Under Armour and changed nothing about whether the
> data was worth having.

Two fixes came out of wiring it up, both general:

- `run.py` now supports `strategy='headless'`, so a client-rendered shop is a
  configuration change rather than a new module.
- `is_candidate` no longer requires one of our brand names in the URL when the
  competitor is a `Marca`. On a brand's own store every product is that brand
  and the name is usually absent from the path, so the filter was rejecting the
  entire catalogue — 7.425 sitemap URLs reduced to 0 candidates.

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

---

## Why the remaining competitors could not be scraped — and what would fix it

Five distinct root causes, not one. They need different solutions, and they are
worth very different amounts.

### A · The data is in embedded page state, not JSON-LD  *(highest value)*

**JD Sports — and, tested afterwards, only JD Sports.**

> **Correction.** This section first claimed the pattern probably extended to
> Deporvillage, Sprinter and Decathlon. It was tested and it does not. Sprinter
> and Decathlon render fully under patchright and publish **neither an EAN in
> their embedded state nor a manufacturer code anywhere on the page** — four
> sampled product pages each, zero matches against our `ref_prov`. Decathlon
> additionally sells mostly its own brands (Kalenji, Kiprun), which we do not
> stock at all, so even solved matching would yield little. Deporvillage still
> refuses product pages outright.
>
> The extractor is still worth building — it unlocks JD Sports and is the right
> shape for the modern web — but the "five largest Spanish retailers" figure was
> wrong. It unlocks **one**.

These sites were recorded as `NO MATCH KEY` — prices present, no identifier.
That verdict was wrong for JD Sports, and the reason matters. Its JSON-LD
carries a single generic offer with no `gtin13`:

```json
{ "@type": "Product", "sku": "E49788E6-…",
  "offers": { "price": 60, "priceCurrency": "EUR" } }
```

while the real per-size data sits in an embedded GraphQL state elsewhere in the
page:

```json
"variants": [{ "sku": "E49788E6-…", "size": "36",
               "ean": "4067889138770",
               "price": { "centAmount": 6000, "formattedValue": "60,00€" } }]
```

EAN **and** price **and** size, per variant — everything the pipeline needs,
in a place the extractor never looked. This is the modern default: Next.js,
Nuxt and Apollo apps serialise their store into the page, and JSON-LD becomes a
thin SEO stub.

There is also a **second identifier hiding in plain sight**: JD Sports' image
URLs contain `jd_IH7759`, the adidas article code, which matches our `ref_prov`.
Several shops leak the manufacturer reference through image paths.

> **Fix:** an `extract_state()` pass alongside the JSON-LD one — find
> `<script>` blocks holding JSON (`__NEXT_DATA__`, `__NUXT__`, `__APOLLO_STATE__`,
> or any large object literal), walk them for objects carrying an `ean`/`gtin`
> and a price, and normalise into the same offer shape. Site-agnostic: one
> parser, many shops.
>
> **Effort:** roughly a day. **Unlocks:** potentially the five largest Spanish
> retailers still missing — Deporvillage (129.330 sitemap URLs), Decathlon
> (86.943), Sprinter (46.187), JD Sports (17.680), Barrabés (30.586).

### B · Genuinely no identifier published

**Barrabés.** Only an internal `sku` (`107725`), no EAN and no manufacturer
reference anywhere on the page. Nothing to join on, and no parser fixes that.

> **Fix:** fuzzy matching on brand + model name, with a confidence score and
> manual review of anything below threshold. Accept that it will be wrong
> sometimes, and never feed it into an automated repricing rule.
>
> **Effort:** 2–3 days including a review UI. **Only worth it for a large seller.**

### C · Client-rendered with nothing extractable

**RunningXpert, Foot Locker, Running Warehouse, Wala.**

> **Correction (2026-09-23).** Décimas was in this group and does not belong
> here. It publishes an EAN and a price for **every size** in a
> `<script id="zandman-data" type="application/json">` block; the extractor was
> rejecting the payload because `json.loads` cannot cope with the CDATA wrapper.
> It is now crawled and contributes 20 models. "Client-rendered with nothing
> extractable" was a statement about my parser, not about the shop.

What the remaining four actually are, after re-testing product pages rather
than the category pages the first probe sampled:

| Shop | Real obstacle |
|---|---|
| **Foot Locker** | 2.200 product URLs, offers render — but **no `gtin13` and no manufacturer code anywhere**. Nothing to join on. Genuinely group B. |
| **Wala** | Its 51.246-URL sitemap is **categories only**; not one product URL. Needs category-page discovery. |
| **RunningXpert** | Same: 11.902 URLs, of which only 32 are products. Category-page discovery. |
| **Running Warehouse** | 466-URL sitemap with 2 shoe entries. Effectively no product sitemap. |

### D · No sitemap declared

**SportsShoes and Salomon** — `robots.txt` is served and permissive but
advertises no sitemap, so there is nothing to enumerate. Salomon was solved by
probing the conventional locations anyway.

> **Correction (2026-09-23).** **Running Emotion, Fútbol Emotion and Basketball
> Emotion were never in this group.** All three declare a sitemap. It is three
> levels deep — root index → `/es/sitemap.xml` → paginated
> `/sitemap/productos/limit/1000/offset/N/` children — and the walker recursed
> only into locs ending in `.xml`, so it returned the *index pages themselves*
> as though they were products. That is why they looked empty.
>
> All three are now crawled, and **Running Emotion is the single largest source
> in the project at 283 models**, with Fútbol Emotion second at 182. They
> publish no GTIN, but their JSON-LD `sku` is the manufacturer article code and
> matches our `ref_prov`.
>
> Category-page discovery is still the right fix for Wala and RunningXpert — it
> was simply never what was wrong with the Emotion shops.

### E · Hard-blocked

**Helly Hansen and Puma** refuse even patchright. **Ekosport** clears Cloudflare
but its sitemaps stay 403 and its catalogue is client-rendered. **Bike24**
declares a sitemap that never returns URLs.

> **Fix:** not a scraping problem. An affiliate feed (both brands run programmes
> through Awin in Spain), a commercial data provider (Minderest, Netrivals —
> both Spanish and already tracking these sites), or Google Merchant Center's
> price-competitiveness report, which keys on the same EANs we already match on.

### Recommended order

| # | Action | Effort | Unlocks |
|---|---|---|---|
| 1 | **Category-page discovery** | ~1 day | Wala, RunningXpert, Running Warehouse |
| 2 | **Browser fetch for sitemaps behind a WAF** | ~2 h | 11teamsports, Alltricks — both 403 on the sitemap itself |
| 3 | Manufacturer code from image URLs | ~2 h | a second key where EANs are absent (JD Sports leaks `jd_IH7759`) |
| 4 | Fuzzy name matching (group B) | 2–3 days | Foot Locker, Barrabés — last resort, needs human review |

Sprinter, Decathlon and Deporvillage remain unreachable by any of them: the
first two publish no usable identifier and the third refuses product pages.

> **The precondition for all of it:** none of this is worth doing while the
> crawls are not scheduled. A wider stale dataset is worth less than a narrower
> fresh one.
