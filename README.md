# Forum Sport · Pricing dinámico

Turns a pricing spreadsheet into a queryable Postgres database on Supabase, with
a landing page that visualises it. Built as teaching material for the **AI
Marketing Lab**, on the way to a dynamic pricing calculator.

**[activities.md](activities.md) is the main document** — a step-by-step log of
how this was built and, more importantly, *why*, including the bugs and what
each one teaches.

## What's here

| | |
|---|---|
| `dataset/` | source spreadsheet (24.109 rows × 30 columns) |
| `scripts/extract_dataset.py` | xlsx → JSON, with 15 assertions built in |
| `scripts/load_supabase.py` | bulk load into Supabase via PostgREST |
| `scripts/verify.sql` | 43 checks against the database |
| `scripts/verify_api.sh` | REST + RLS checks with the public key |
| `supabase/migrations/` | schema, RLS, views, hardening, image URLs |
| `index.html` | the landing page (no build step, no dependencies) |
| `scripts/scraper/` | competitor price-scraping agent |
| `SCRAPING.md` | what is crawled, how politely, and how to add a site |
| `crawler_info.md` | per-competitor crawling guide and evaluation results |
| `API.md` | endpoints, with responses captured from the live project |
| `competitors.md` | competitor list, transcribed from the source spreadsheet |

## The data

One row per SKU, with model attributes repeated across every size. Verified to
split losslessly into **1.483 models × 24.109 SKUs × 28 brands**.

| | |
|---|---|
| Average PVP | 145,59 € |
| Models discounted | 824 (55,6 %) at 27,4 % average |
| Average margin | 27,6 % |
| Stock "muy bajo" | 1.027 models (69 %) |

The tension this project exists to address: **60,2 % of the lowest-stock tier is
discounted, against a 55,6 % catalogue average.** The products with least left
to sell are the most marked down.

## Running it

```bash
cp .env.local.example .env.local     # then fill in your Supabase keys
python3 scripts/extract_dataset.py   # no credentials needed
python3 scripts/load_supabase.py     # needs the service_role key
./scripts/verify_api.sh              # needs the anon key
python3 -m http.server 8000          # then open http://localhost:8000
```

Apply `supabase/migrations/*.sql` in numerical order.

## Notes

- `.env.local` is gitignored. The **anon** key is safe in the browser (RLS
  restricts it to reads); the **service_role** key bypasses RLS and is
  server-side only.
- Derived values live in the database as generated columns — `neto`,
  `descuento_pct`, `en_rebaja`, `url`, `img_thumb`. The frontend never
  recomputes business logic.
