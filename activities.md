# Dynamic Pricing Calculator · Forum Sport — Activity Log

Running record of how this project is built, kept as raw material for an
**AI Marketing Lab** tutorial. Each activity records *what* was done, *why*, and
the *lesson* worth teaching — because the reasoning is the part students can
reuse on a different dataset.

**Project goal:** turn a pricing spreadsheet into a queryable database and,
on top of it, a Dynamic Pricing Calculator with a landing page.

| | |
|---|---|
| Started | 2026-09-22 |
| Source data | `dataset/Dataset_FS_pricing_dinámico.xlsx` (3.5 MB, 3 tabs) |
| Database | Supabase (Postgres) — new dedicated project |
| Tooling | Claude Code + Supabase MCP server, Python 3 (stdlib + openpyxl) |

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Understand the dataset | Done |
| 2 | Design the data model | Done |
| 3 | Build the pipeline (schema, transform, loader) | Done |
| 3b | Dry run on a local Postgres | Done — 43/43 checks pass |
| 4 | Provision Supabase + load the data | Done |
| 5 | Verify against ground truth | Done — 43/43 SQL + all API checks |
| 6 | Document the API for the frontend | Done — `API.md` |
| 7 | Landing page | Done |
| 8 | GitHub and Vercel deployment | Done |
| 9 | Competitor price scraping | Done — 10 competitors live |
| 10 | Re-examining the "unscrapable" sellers | Done — 16 live, 38,5 % of catalogue |
| 11 | Dimension filters + positioning time series | Done |
| 12 | Dynamic Pricing Calculator | Not started |

---

## Phase 1 — Understand the dataset

### 1.1 Inventory before writing any code

Opened the workbook read-only and listed its tabs before assuming anything:

| Tab | Size | What it really is |
|---|---|---|
| `campos` | 30×5 | **Data dictionary** — which fields are model-level vs SKU-level |
| `valores dimensiones` | 81×9 | **Pivot tables** — totals per dimension |
| `bbdd` | 24.110×30 | The data itself |

> **Lesson.** The two "boring" tabs turned out to be the most valuable. `campos`
> explained the business grain and even documented the public product-URL
> pattern; `valores dimensiones` became the test oracle for the whole pipeline.
> Read the documentation tabs before the data tab.

### 1.2 Profile every column

Rather than eyeballing rows, every one of the 30 columns was profiled for null
count, blank count, distinct values, max length and Python type. That surfaced
the problems that would otherwise have failed at load time:

- `COBERTURA (STOCK)` mixes integers with the string `SIN DATOS COBERTURA`
- `ABCD_Tienda` / `ABCD_Digital` use `SIN DATOS CLASIFICACIÓN` instead of blank
- `Exclusivoonline`, `Outlet`, `Cat.extendido`, `Online` are booleans in disguise
  (`''`/`'ExclusivoOnline'`, `NO`/`SI`, `0`/`1`, constant `'online'`)
- `Ano Temporada` uses `9998` as an "unknown year" sentinel (2 models)
- `Talla` holds half sizes (`7.5`) → not an integer
- 7 SKUs carry `talla_es = 0`, an unmapped size

> **Lesson.** Spreadsheets encode "missing" as words (`SIN DATOS…`), blanks and
> magic numbers (`9998`), all in the same column. A database forces you to pick
> one representation — `NULL` — and that decision is business analysis, not
> data cleaning. Profile first; a mixed-type column always means a hidden rule.

### 1.3 Find the real grain

Counting confirmed the sheet is **one row per SKU**, not per product, with
model attributes repeated across every size:

- 24.109 data rows, but only **1.483 distinct `Modelo`** values
- `Modelo` = product + colour (per `campos`): the black Novablast 6 and the blue
  one are different models
- each model has ~16 sizes on average, each an independent SKU (`material`)

> **Lesson.** "One row = one product" is almost never true in retail exports.
> Establish the grain before designing tables, or you will average prices over
> shoe sizes and report nonsense.

### 1.4 Prove the split is safe

Before normalizing, the assumption was **tested, not trusted**: for each of the
1.483 models, do the 25 model-level columns hold exactly one distinct value?

```
MODEL-LEVEL COLS THAT VARY WITHIN A Modelo: NONE — all constant
```

Also verified: `Material` and `Ean` unique across all 24.109 rows; brand code →
brand name is a clean 1:1 over 28 brands; `Rebaja2 > Precio2` never happens.

> **Lesson.** Normalization is only lossless if the redundancy is genuinely
> redundant. One query answers it. Skipping that check is how you silently drop
> data on 3 of 1.483 products and never notice.

### 1.5 Detect a derived column

Tested a hunch about the pricing formula across all 24.109 rows:

```
NETO SINTÉTICO* = Rebaja2 × (1 − MARGEN SINTÉTICO*)      → 0 mismatches
```

So `neto` is not data — it is a **calculation**, and it is the seed of the
pricing calculator. Stored as a Postgres generated column instead of being
imported.

> **Lesson.** Recomputing a column and diffing it against the file tells you
> whether it is an input or an output. Outputs belong in the database as
> generated columns: one definition, impossible to drift, no frontend maths.

---

## Phase 2 — Design the data model

### 2.1 Three tables

| Table | Rows | Holds |
|---|---|---|
| `brands` | 28 | code → commercial name |
| `models` | 1.483 | identity, season, management flags, **pricing**, stock |
| `skus` | 24.109 | `material`, `talla`, `talla_es`, `ean` |

Storing pricing once per model instead of once per SKU removes ~16× duplication
and makes a price change a single-row update.

### 2.2 Push business logic into the database

Generated (`stored`) columns on `models`:

| Column | Definition |
|---|---|
| `neto` | `precio_rebaja * (1 - margen)` — the verified source formula |
| `descuento_pct` | `round((precio - precio_rebaja) / precio * 100, 2)` |
| `en_rebaja` | `precio_rebaja < precio` |
| `url` | `'https://www.forumsport.com/es-es/-' || modelo || '-p'` |
| `nivel_margen_orden`, `nivel_stock_orden` | `muy bajo → muy alto` as 1–5 |

The ordering columns exist because `muy bajo, bajo, medio, alto, muy alto` sorts
wrongly alphabetically. Solving it once in SQL beats a lookup map in every chart.

> **Lesson.** Anything every consumer would have to recompute belongs in the
> database. The API then hands the frontend answers, not ingredients.

### 2.3 Constraints as documentation

`CHECK` constraints pin the allowed values (`temporada in ('AN','OI','PV')`,
four margin values, five stock levels, `precio_rebaja <= precio`). They document
the domain *and* make a bad future load fail loudly instead of quietly.

> **Lesson.** A constraint is a test that runs on every insert, forever.

---

## Phase 3 — Build the pipeline

### 3.1 Files

```
supabase/migrations/001_schema.sql   tables, constraints, generated cols, indexes
supabase/migrations/002_rls.sql      row level security + public read policies
supabase/migrations/003_views.sql    10 reporting views for the landing page
scripts/extract_dataset.py           xlsx -> data/*.json  (no credentials)
scripts/load_supabase.py             data/*.json -> PostgREST, batches of 1.000
scripts/verify.sql                   counts asserted against the pivot oracle
scripts/verify_api.sh                REST checks with the public anon key
```

### 3.2 Separate transform from load

`extract_dataset.py` reads the spreadsheet and writes JSON. It needs no
credentials and no network, so it can be run, reviewed and re-run freely.
`load_supabase.py` only moves finished JSON to Supabase.

> **Lesson.** Splitting "reshape the data" from "send the data" means a load
> failure is never also a transform mystery — and students can run step one
> without any account at all.

### 3.3 Turn the pivot tab into automated tests

The `valores dimensiones` pivots were built by someone else, from the same data,
without our code — a genuinely independent **oracle**. They are encoded as 15
assertions that run at the end of the transform:

```
Validated against the workbook pivots: 28 brands, 1483 models, 24109 skus.
  wrote     28 records -> data/brands.json
  wrote  1,483 records -> data/models.json
  wrote 24,109 records -> data/skus.json
```

Each dimension total is checked (running 984 / trail 499; margin levels
287/261/601/334; stock levels 58/63/66/269/1027; outlet 112; extended category
478; online-exclusive 682; seasons 48/1040/395; the full ABCD breakdown), plus
structural checks for duplicate EANs and orphan SKUs.

> **Lesson.** Spreadsheets usually ship their own answer key in a pivot tab.
> Encoding it as assertions converts "looks right" into "provably right", and it
> catches the error that matters most: a pipeline that runs fine and is wrong.

### 3.4 Ten views, ten charts

One view per landing-page visualization (`v_kpis`, `v_por_marca`,
`v_por_nivel_margen`, `v_por_nivel_stock`, `v_por_temporada`, `v_abcd_matriz`,
`v_por_tipo_producto`, `v_bandas_precio`, `v_curva_tallas`,
`v_modelos_detalle`) so the frontend makes one small request per chart instead
of downloading 1.483 models and aggregating in the browser.

A subtle bug avoided in `v_por_marca`: joining `models` to `skus` and averaging
price would weight each model by its number of sizes. SKU counts are computed in
a separate CTE so averages stay at model grain.

> **Lesson.** Aggregating after a one-to-many join silently weights your
> averages. It is the most common bug in retail dashboards.

### 3.5 Security model

RLS on all three tables, with a `select`-only policy for `anon`. No write
policies exist, so anonymous writes are refused by default. Views are
`security_invoker` so they honour the caller's policies. The loader uses the
`service_role` key (which bypasses RLS, server-side only); the frontend gets the
`anon` key. `.env.local` is gitignored, and `.mcp.json` expands the token from
the environment rather than hardcoding it.

> **Lesson.** "Public data" still needs RLS — public means *readable*, not
> *writable*. Two keys, two audiences: never let the service key reach a browser.

### 3.6 Why the bulk load does not go through MCP

Schema changes and verification go through the Supabase MCP server. The 24.109
rows do not: as SQL literals that is dozens of very large tool calls, versus ~25
HTTP requests from a script. The loader is idempotent
(`Prefer: resolution=merge-duplicates`), so re-running upserts rather than fails.

> **Lesson.** Use each tool where it is strong — MCP for schema and inspection,
> plain HTTP for bulk data. And make loaders re-runnable: you will run them again.

### 3.7 Rehearse the whole thing on a throwaway database

Before creating anything in Supabase, the full pipeline was run against a
disposable Postgres 16 container:

```
docker run --rm -d --name fs_pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=forum postgres:16
```

Steps: create the `anon` / `authenticated` roles Supabase normally provides,
apply the three migrations, `COPY` the real 24.109 rows in, run `verify.sql`,
query every view, then delete the container.

**It found a real bug.** `verify.sql` labelled each assertion `as check` —
and `check` is a reserved word in Postgres:

```
ERROR:  syntax error at or near "check"
LINE 61:   check, want, got
```

Renamed to `prueba`. Then:

```
 status |         prueba          | want  |  got
--------+-------------------------+-------+-------
 PASS   | models = 1483           | 1483  | 1483
 PASS   | skus = 24109            | 24109 | 24109
 ... 43 rows, all PASS
```

The rehearsal also confirmed things no amount of reading can:

- every `CHECK`, `NOT NULL`, unique and foreign-key constraint survives contact
  with all 24.109 real rows
- generated columns compute correctly — model `1001071778`: 140 € → 70 €,
  `descuento_pct` 50.00, `neto` 59.50 = 70 × (1 − 0.15)
- **RLS behaves**: as `anon`, every read works and `INSERT` / `UPDATE` /
  `DELETE` are all refused with `permission denied`
- the views return sane business numbers that cross-foot: 16.413 + 7.696 =
  24.109 SKUs; the nine price bands sum to 1.483 models

First real numbers out of the dataset:

| KPI | Value |
|---|---|
| Models / SKUs / brands | 1.483 / 24.109 / 28 |
| Average PVP | 145,59 € |
| Average sale price | 123,12 € |
| Models discounted | 824 (55,6 %) |
| Average discount | 27,4 % |
| Average margin | 27,6 % |
| Stock level "muy bajo" | 1.027 models (69 %) |

> **Lesson.** A throwaway container costs a minute and turns "the migration
> should work" into "the migration ran, on the real data, and every check
> passed". Rehearse against local infrastructure before touching the live
> project — especially when the live step is the one you cannot easily undo.

> **Lesson (business).** The profile already tells a pricing story: 69 % of
> models sit at "muy bajo" stock while 56 % are discounted. Those two facts
> together are precisely what a dynamic pricing calculator should question —
> discounting product you barely have is margin given away for nothing.

---

## Phase 4 — Provision Supabase and load

Connecting the tooling took three attempts. All three failures are worth
teaching, because students will hit every one of them.

### 4.1 An MCP server that is configured is not yet available

`/Users/igorostiza/forum` had no MCP configuration at all, so no Supabase tool
existed in the session. Writing `.mcp.json` does not fix that *in the running
session*: MCP servers are launched at startup.

> **Lesson.** Adding an MCP server mid-session does nothing until you restart
> the client and approve the server. Configured ≠ loaded ≠ approved.

### 4.2 `.mcp.json` expands the environment, not your `.env` file

The first config used `"${SUPABASE_ACCESS_TOKEN}"`, which Claude Code expands
from the **process environment**. Pasting the token into a `.env` file would
therefore have silently produced an unauthenticated server.

Rather than force the token into `~/.zshrc`, the server command now sources the
env file itself, so credentials live in exactly one gitignored place:

```json
"command": "sh",
"args": ["-c", "set -a; [ -f \"$0\" ] && . \"$0\"; set +a; ... exec npx -y @supabase/mcp-server-supabase@latest",
         "/Users/igorostiza/forum/.env.local"]
```

The first version of that line used `dirname "$0"` and silently read nothing —
`$0` was already the directory, and `dirname` walked one level too far up. It
was caught only because the wrapper was executed and the variable printed.

Two knock-on fixes: the `.env.local` template was rewritten with **quoted**
values, because a placeholder like `https://<project-ref>.supabase.co` contains
`<`, a shell redirect that breaks `source`.

> **Lesson.** Environment variables are not files. Whenever a tool says it reads
> `$VAR`, ask *whose* environment — and then prove it by echoing the value from
> inside the same wrapper the tool will use. A silently empty variable is the
> worst failure mode: everything starts, nothing authenticates.

### 4.3 A broken Node install

The smoke test then failed outright:

```
(eval):1: command not found: node
```

Homebrew's `node` 25.4.0 was a **dangling symlink** — `Cellar/node/25.4.0/bin/`
contained `npm` and `npx` but no `node` binary, so `npx` (shebang
`#!/usr/bin/env node`) could never run. An nvm-managed Node v24.13.0 was present
and healthy, so the wrapper now prepends the first working nvm `bin` to `PATH`.

Verified end to end by speaking MCP to the server over stdin:

```
{"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},
 "serverInfo":{"name":"supabase","title":"Supabase","version":"0.13.0"}...
```

> **Lesson.** Smoke-test the server *before* the restart that depends on it.
> "MCP server won't connect" is usually not MCP — it is PATH, a broken runtime,
> or a credential that never arrived.

### 4.4 Creating the project

After the restart the tools appeared and the project was created through MCP:
`list_organizations` → `get_cost` → `confirm_cost` → `create_project`.

`get_cost` had to be called **per organization**, and the answer was not the
same: of the three orgs available, two quoted **$0/month** and one **$10/month**.
Supabase's MCP deliberately forces an explicit cost confirmation before it will
create anything — `confirm_cost` returns a token that `create_project` requires.

| | |
|---|---|
| Project | `forum-sport-pricing` |
| Ref | `hhehxwdpvoojgjbogton` |
| Region | `eu-west-3` (Paris — closest to Spain) |
| Postgres | 17.6 |
| Cost | $0/month (free tier) |

The first `apply_migration` failed with a bare `TypeError: fetch failed` even
though the API already reported `ACTIVE_HEALTHY`. The project's database
endpoint simply was not resolvable yet; a trivial `select version()` a moment
later succeeded, and the migration then applied first time.

> **Lesson.** "Created" and "reachable" are different events in cloud
> provisioning, and the status field can lie about the gap. When a brand-new
> resource refuses the first call, probe it with the cheapest possible query
> before assuming the request was wrong.

### 4.5 Schema applied, and a security check that passes for a reason

All three migrations applied cleanly. `list_tables` confirms
`rls_enabled: true` on all three tables, and Supabase's security advisor
returns **zero findings**:

```
get_advisors(type="security")  ->  {"lints": []}
```

That clean result is not luck. The advisor's two most common complaints are
*"table public.X has no RLS"* and *"view public.Y is SECURITY DEFINER"* —
avoided by `002_rls.sql` and by declaring every view
`with (security_invoker = on)`.

> **Lesson.** Run the security advisor immediately after every DDL change, not
> at the end of the project. It is a free review of exactly the mistakes that
> are embarrassing to find in production.

### 4.6 The one secret the MCP will not give you

The loader still needs the **`service_role`** key, and there is no MCP tool that
returns it. `get_publishable_keys` hands over only the `anon` and publishable
keys — the ones that are safe in a browser. The secret key must be copied by a
human from the dashboard.

> **Lesson.** That asymmetry is a deliberate design, and a good thing to show
> students: an agent can freely obtain the keys that are safe to publish, while
> the key that bypasses RLS stays behind a human step.

## Phase 5 — Verify

### 5.1 The load

```
brands       28/28  done
models    1,483/1,483  done
skus     24,109/24,109  done
```

25.620 rows in **9,2 segundos**, in ~26 HTTP requests.

It failed on the first attempt, for a reason that has nothing to do with
Supabase:

```
[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
```

The python.org build of Python on macOS ships **no root certificates** and
verifies nothing against the system keychain. `certifi` was already installed,
so the loader now builds its SSL context from `certifi.where()` and falls back
to the system defaults when it is absent.

> **Lesson.** `CERTIFICATE_VERIFY_FAILED` on macOS is almost never the server's
> certificate. It is Python not knowing where the trusted roots are.

### 5.2 43/43 against the live database

`verify.sql`, run through MCP `execute_sql`, reproduced the local result exactly:

```
pass | fail | failures
  43 |    0 | none
```

The workbook's pivot totals now hold in Supabase: 984/499 by product type,
287/261/601/334 by margin level, 58/63/66/269/1027 by stock level, the full ABCD
breakdown, zero orphan SKUs, zero mis-computed `neto`.

> **Lesson.** Run the same assertions locally *and* in production. Passing
> locally proves the transform; passing in production proves the load arrived
> whole. They are different claims, and only the second one ships.

### 5.3 The security test that nearly passed for the wrong reason

The API test attempted anonymous writes. Two came back **`204 No Content`**:

```
FAIL  DELETE skus    NOT rejected [204]
FAIL  PATCH  models  NOT rejected [204]
```

The data turned out to be untouched — 24.109 SKUs, target row present, price
still 140,00 €. RLS *had* blocked the writes. But PostgREST answers `204`
because, with the rows filtered away by RLS, the statement legitimately matched
**zero rows** — and deleting nothing is a success.

Checking the grants revealed the real picture:

```
anon -> brands: DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
```

Supabase's default privileges grant **ALL** on every new object in `public` to
`anon` and `authenticated`. The `grant select` in `002_rls.sql` was redundant;
the write grants were already there, and **RLS was the only thing between the
public internet and the data**. One person disabling RLS on a table — a normal
thing to do while debugging — would have made it world-writable.

`004_revoke_public_writes.sql` strips those privileges and sets the same rule
for objects created later:

```sql
revoke all on all tables in schema public from anon, authenticated;
grant select on all tables in schema public to anon, authenticated;
alter default privileges in schema public
  revoke insert, update, delete, truncate on tables from anon, authenticated;
```

`anon` now holds `SELECT` and nothing else across all 13 objects, and the write
attempts are refused outright at `401`.

> **Lesson (the important one).** A green test can be green for the wrong
> reason. "The API returned an error code" is a *proxy* for "the data is safe";
> the test that matters re-reads the data and proves it did not change. The
> rewritten test now does both — and it was the weak assertion, not the strong
> one, that exposed a genuine hole in the permissions.

> **Lesson.** Defaults are part of your security model even when you did not
> write them. Read the grants; do not infer them from the migration you wrote.

### 5.4 Two smaller findings

- An unfiltered `DELETE` returns **400**, not 401: PostgREST refuses to delete
  without a `WHERE` clause. Also a rejection, and a sensible guardrail.
- The test queried `v_modelos_detalle?marca_codigo=…`, but that view exposes
  `brand_code`. A 400 with `column does not exist` — the kind of naming drift
  that only surfaces when something actually calls the endpoint.

### 5.5 Advisors

```
get_advisors(security)    -> 0 findings
get_advisors(performance) -> 3 INFO: unused index
```

The unused indexes are on `brand_code`, `nivel_margen_orden` and
`nivel_stock_orden` — expected on a database with no frontend yet, and exactly
the columns the landing page will filter on.

## Phase 6 — API documentation

`API.md` documents every endpoint with a response captured from the live
project, plus `supabase-js` snippets, filtering and pagination, and the data
quirks a frontend must handle: `numeric` arrives as a **string**, `9998` is a
sentinel year, `cobertura_stock` is `null` for 249 models, `brand_code` and
`marca_codigo` differ between views.

> **Lesson.** Documentation written from responses you actually received beats
> documentation written from the schema. Only the first kind catches
> `"precio": "140.00"` arriving as a string.

## Phase 7 — The landing page

A single `index.html`: no build step, no chart library, no framework. It reads
the database directly over PostgREST with the public `anon` key.

### 7.1 Fetch once, filter in the browser

The page pulls all 1.483 models in two requests (PostgREST caps a response at
1.000 rows) and computes every aggregate client-side, instead of calling the ten
reporting views.

That is a deliberate reversal of the Phase 3 design, for one reason: **filters
must scope every chart at once.** With the aggregation in the browser, picking
"NIKE" instantly re-derives the hero figure, all six charts and the table from
the same 239 rows. Hitting pre-aggregated views would need a round trip per
chart and risk them disagreeing mid-flight. At 1.483 rows (~300 KB) the tradeoff
is free; at 100.000 it would not be, and the views would win.

> **Lesson.** "Aggregate in SQL" and "aggregate in the client" are not a matter
> of taste — they are a function of row count and interaction. Know which one
> your data size is buying you.

### 7.2 Colour was computed, not chosen

The palette was **run through a validator**, not eyeballed:

```
Palette (light, categorical): 2 slots
  [PASS] CVD separation   worst pair ΔE 24.7 (protan)
  [PASS] Contrast vs surface   all 2 >= 3:1
```

The first ordinal ramp attempt **failed** — two blue steps were too close to
tell apart (`ΔL 0.049`, floor `0.06`). Re-stepping the ramp fixed it. Both modes
were validated separately against their own surface; dark mode is a *selected*
set of steps, not an inverted light mode.

> **Lesson.** Colourblind-safety is arithmetic, not judgement. "These look
> different enough" is how you ship a chart a twelfth of men cannot read.

### 7.3 Three bugs the screenshot caught

Rendering the page and *looking at it* found what the code review did not.

**A chart that encoded two different things at once.** "Rebaja frente a stock"
drew bar length from the model *count* while printing the *percentage* beside
it — so a 60,2 % label sat on a bar four times longer than a 52,4 % one. Rebuilt
as a 100 % stacked bar: every row is the same length, so length and label now
say the same thing, and the counts moved to `n =` labels and the tooltip.

**Axes with too much headroom and fractional ticks.** A max of 1.027 was drawn
on an axis to 2.000, and tick labels read `62,5`. The scale function now derives
a clean step from ~5 intervals and then takes only as many steps as the data
needs — 1.027 now ends at 1.250.

**Labels whose colour never applied.** In-bar labels were set with
`fill="#fff"`, but a CSS rule (`.val{fill:…}`) silently overrode it — **CSS
beats SVG presentation attributes.** The fix picks ink or white per fill by
luminance: black on orange measures 6,8:1 against white's 3,1:1, so the
"obvious" white label was also the wrong one.

> **Lesson.** Step seven of a chart is "render it and look at it". A validator
> checks colour, not whether the geometry tells the truth.

### 7.4 Mobile overflow: the `min-width:auto` trap

At 390 px the page scrolled sideways. The offender was a grid item 597 px wide
inside a 390 px viewport: **grid and flex items default to `min-width:auto`**,
so a 7-column table inside a card refuses to shrink and stretches its track.
`min-width:0` on the grid items plus an `overflow-x` wrapper on the tables fixed
it — the page now fits and the table scrolls inside its own card.

> **Lesson.** Almost every "my grid won't shrink" bug is `min-width:auto`.

### 7.5 Pagination: the table became the catalogue

The table listed the top 12 discounts. Paginating 12 rows means nothing, so the
table now holds **every model in the current filter** — 1.483 by default, 124
pages — still ordered by discount, so the first page is the same "mayores
descuentos" view it replaced.

The paging state lives inside the table's own closure and redraws only the
`tbody` and the pager, not the page. That matters because `render()` rebuilds
everything from scratch: had the page number lived in the global filter state,
every click would have re-derived all six charts to change twelve rows.

Edge cases were tested rather than assumed, and each one is a real bug if left:

| Case | Expected | Result |
|---|---|---|
| Last page of 1.483 at 12/page | 7 rows, `next` disabled | 124/124, 1477–1483 |
| Click `next` on the last page | no movement | clamped |
| Change 50 → 12 per page | keep roughly the same rows | page 2 → page 5 |
| Filter to 4 results | 1 page, both buttons off | `1 / 1`, both disabled |
| Filter while on page 7 | reset to page 1 | reset |

> **Lesson.** Pagination is four lines of arithmetic and about six edge cases.
> The arithmetic is never what breaks — an off-by-one on the last page, or a
> stale page number after a filter shrinks the result set, is what ships.

### 7.6 Product images, reverse-engineered

From one example URL, tested rather than assumed:

```
/images/{slug}-lateral-exterior-{modelo}-{size}-f
```

| Test | Result |
|---|---|
| Correct slug vs **junk slug** | byte-identical image → the slug is decorative |
| Remove `lateral-exterior` | `200` with a **zero-byte body** |
| `300x300`, `400x400`, `600x600` … | `200` with **0 bytes** — only 200/500/1000 exist |
| 26 models across the 12 biggest brands | **26/26** had an image |

The example URL's trailing number (`1001142165`) was **not** a `modelo` in our
database — checking that first is what prompted testing whether the ID even
mattered. It does; everything around it mostly does not.

The pattern became two generated columns (`img_thumb`, `img_full`), keeping the
project's rule that derived values live in the database.

> **Lesson.** An endpoint that returns `200` with an empty body is worse than a
> 404: it looks like success. When reverse-engineering an API, assert on the
> **response size**, not the status code.

> **Lesson.** Vary one part of a URL at a time and you learn which parts are
> load-bearing. Copying the example verbatim would have worked — and taught
> nothing about what happens for the other 1.482 models.

## Phase 8 — GitHub and Vercel

Repo: **private** `inakigorostiza/forum-sport-pricing` · live at
**https://forum-sport-pricing.vercel.app**

### 8.1 Private, on purpose

The dataset holds a real retailer's margins, net prices and stock coverage.
A public repo would publish a competitor's dream document, permanently — git
history keeps it even if the file is deleted later. Private was the default
before anything was pushed.

Before the first commit the staged files were scanned for credentials. The only
JWTs present decode to `role=anon`, which is safe by design; `.env.local` and
the generated `data/` were correctly excluded by `.gitignore`.

> **Lesson.** Check what you are about to publish *before* the first push, not
> after. Git history is not an undo button.

### 8.2 The deploy that undid the privacy

The first Vercel deployment went live, and the repo was private — so the data
was safe. It was not:

```
GET /dataset/Dataset_FS_pricing_dinámico.xlsx   200   3.571.537 b
GET /supabase/migrations/001_schema.sql         200       5.824 b
GET /scripts/load_supabase.py                   200       4.124 b
```

**A static Vercel deployment serves every file in the repository.** The entire
commercial spreadsheet was downloadable by anyone with the URL. Repository
visibility and deployment visibility are two completely different controls, and
only the first had been set.

`.vercelignore` now limits the deployment to the landing page. Re-verified:

```
/dataset/...xlsx  404     /scripts/load_supabase.py  404
/activities.md    404     /                          200
```

The exposure lasted about 46 seconds on the production alias. The older
per-deployment URL turned out to be SSO-protected, so the window was limited to
that alias.

> **Lesson (the one to teach).** "The repo is private" says nothing about what
> your deployment serves. After every first deploy, *request the files you
> expect to be secret* and confirm they 404. Assume a static host publishes
> everything unless you tell it otherwise.

### 8.3 A 403 that was not a bug

The live site was tested with a headless browser and rendered nothing, with two
`403`s. The body explained it: **"Vercel Security Checkpoint"** — bot protection
reacting to the headless fingerprint, not a fault in the page. `curl` had
returned `200` all along. Re-run with an ordinary user agent, the live site
loaded 1.483 models, 7 cards, 43 marks and 12 thumbnails with zero errors.

> **Lesson.** Read the error body before believing the status code. A `403` from
> a bot-protection layer and a `403` from your own API look identical in a log
> and mean completely different things.

## Phase 9 — Competitor price scraping

The catalogue answers *what we charge*. This phase answers *what everyone else
charges*, which is the half the pricing question actually turns on.

Full operational detail is in [crawler_info.md](crawler_info.md) and
[SCRAPING.md](SCRAPING.md); this is what was learned.

### 9.1 The EAN is the whole design

24.108 of our 24.109 SKUs carry a globally resolvable GS1 code, and most shops
publish `gtin13` in their structured data. So matching is exact — no fuzzy name
comparison, no manual mapping.

The trap is that **50,7 % of our EANs are stored as 12-digit UPCs** while
competitors publish 13 digits. A direct join loses half the catalogue and raises
no error at all. Both sides are normalised to 13 digits. In the first real
crawl, **20 of 26 matched models came through 12-digit EANs** — without the
padding, 6.

> **Lesson.** The dangerous data bugs are the ones that return a plausible
> answer. A join that silently halves your data looks exactly like a join that
> works.

### 9.2 Brands need a second key

adidas and Nike publish **no GTIN at all**, so the EAN path cannot work for
them. What they do expose is the manufacturer article code, which is exactly
what our catalogue stores as `ref_prov` — 230 of our 231 adidas models carry an
adidas-shaped code.

adidas puts it in the URL, so their catalogue can be intersected with ours
*before* fetching: 66 pages instead of 15.337. Nike hides it behind opaque
slugs, so the match is decided after fetching, and its `mpn` carries a colour
suffix (`HV8116-001` → `HV8116`).

Both are **model-level** matches, while a GTIN match is **size-exact**. The
database records `match_method` on every offer so the two are never conflated.

> **Lesson.** One identifier is a design; two identifiers with different
> precision is a design decision that has to be written down, or someone will
> average them together later.

### 9.3 Bot protection, and where the line is

| Site | Plain HTTP | Headless Chrome | Chrome + stealth | Patchright |
|---|---|---|---|---|
| adidas | 403 | 403 | 403 | **passes** |
| Nike | 403 | — | — | **passes** |
| Tradeinn | **passes** | — | — | not needed |

adidas's `robots.txt` explicitly *allows* product pages; it is the Akamai WAF,
not the stated policy, that refuses. That distinction was worth establishing
before deciding anything.

> **Lesson.** Check what a site's policy says separately from what its
> infrastructure does. They disagree more often than you would expect, in both
> directions — Decathlon publishes a permissive `robots.txt` and 403s its own
> homepage.

### 9.4 The bug that hid the biggest competitor

`_ld_nodes` only flattened `@graph`, so a `Product` nested inside
`WebPage.mainEntity` was invisible and the page reported "no offers". That is
exactly how **Tradeinn** publishes — the largest seller on the list, 69.368
records. One fix turned it from "no structured data" into 9 offers with 9 GTINs,
over plain HTTP, no browser needed.

It also invalidated five earlier verdicts I had recorded as findings about those
sites.

> **Lesson.** When a whole class of sites fails the same way, suspect the
> parser before the sites.

### 9.5 Judging a site on too little evidence

I declared Bergfreunde and Top4Running dead on 5-page samples with 0 matches. At
300 pages they are the second and fifth largest sources — **1.120 and 769
offers**. Viladomat, tested the same way, really is dead: 0 from 300.

I also reported i-Run, Deporvillage and Sprinter as "403 blocked" on the
strength of a single homepage `curl`. None of them are blocked. i-Run is fully
crawlable and matching; Deporvillage serves 129.330 sitemap URLs and Sprinter
46.187, both with real prices.

> **Lesson.** A negative result needs at least as much evidence as a positive
> one. "I tried and it didn't work" is not a finding until you have tried enough
> to distinguish *doesn't work* from *didn't look hard enough*.

### 9.6 A fallback that made things worse

The evaluator retries blocked sites with patchright. When the browser attempt
failed on a site whose HTTP attempt had **succeeded**, the failure replaced the
success — Wala went from 102.493 sitemap URLs to "sitemap unreadable". All 28
evaluations came back empty, which is what made it obvious.

The cause was a unit mismatch: `timeout` was seconds in one fetcher and
milliseconds in the other, so `timeout=60` gave the browser 60 ms. The retry is
now only accepted when it moves *up* the verdict ranking.

> **Lesson.** A fallback must never be able to overwrite a better answer, or its
> failures masquerade as findings about the thing you were measuring.

### 9.7 What the data says

Six competitors live, **312 models compared**:

| Competitor | Models | We are cheaper | Average gap |
|---|--:|--:|--:|
| Nike | 93 | 23 | +6,5 % |
| Bergfreunde | 73 | 10 | +10,8 % |
| adidas | 66 | **54** | **−5,9 %** |
| Tradeinn | 52 | 8 | **+21,2 %** |
| Top4Running | 42 | 10 | +12,6 % |
| Atmósfera Sport | 26 | 5 | +7,2 % |

Every competitor added made the picture worse — the headline gap moved **+1,8 %
→ +5,9 % → +8,0 %** against us. adidas was flattering the average: it is the
only seller we systematically undercut, which is what you would expect of a
stockist against the brand's own RRP.

The remaining obstacle is **not access — it is missing identifiers**. Five large
retailers serve big sitemaps and real prices but publish neither `gtin13` nor
`mpn`. Solving that unlocks more coverage than any further bot evasion.

## Phase 10 — Re-examining the sellers that "could not" be scraped

Fourteen sellers had been written off across earlier passes. Re-testing them
with the tools built since — undeclared-sitemap probing, a gzip→browser
fallback, and the embedded-state extractor — took coverage from **10
competitors / 406 models to 16 / 571**, which is **38,5 % of the catalogue**.

**Six were recovered. Every one failed for a reason inside our crawler.**

| Seller | Models | The actual defect |
|---|--:|---|
| Running Emotion | 283 | sitemap walker recursed only into `.xml` children |
| Fútbol Emotion | 182 | same, plus the domain name tripped our own EXCLUDE filter |
| Basketball Emotion | 53 | same, plus an article-code match that was too strict |
| Décimas | 20 | a CDATA wrapper broke `json.loads` on a payload full of EANs |
| Viladomat | 14 | `--limit` sampled the head of a brand-grouped sitemap |
| The North Face | 3 | global sitemap never reached `/es-es/`; 403s our honest UA |

> **Lesson — a negative result about someone else is usually a bug in your own
> code.** Not one of these six was blocked, rate-limited or missing data. Each
> had published everything we needed the whole time. The earlier verdicts —
> "client-rendered with nothing extractable", "no sitemap declared", "genuinely
> dead, 0 from 300" — were all descriptions of our parser, phrased as facts
> about the shop. **Before recording a negative, prove the failure is theirs.**

> **Lesson — where you sample decides what you find.** Viladomat was declared
> dead on 300 pages. `--limit` takes the *head* of the candidate list, sitemaps
> are grouped by brand, and those 300 pages were brands we do not stock. A
> stride across the same list hit 16 matches in 10 pages. Sample with a stride,
> never from the head.

> **Lesson — a silent `continue` destroys a diagnosis.** The probe discarded
> failed fetches with `if not html: continue`, so "blocked by the WAF" and
> "publishes no structured data" produced an identical verdict. Nine of ten
> "dead" sites had failed at discovery; only one was truly blocked. **Never let
> two different causes share one error path.**

### A defect this surfaced

The crawler accepted an offer when the part of the competitor's article code
before the first hyphen matched our `ref_prov`, but `v_ofertas_emparejadas`
required the two to be *equal*. Offers were stored and then silently dropped
before reaching the landing page — Basketball Emotion wrote 10 Nike offers and
produced zero comparison rows.

Neither rule alone is correct, because the two sides carry colour differently:

| Brand | Our `ref_prov` | Their `mpn` | Needs |
|---|---|---|---|
| NIKE | `CD4371` | `FQ7262-103` | base match |
| SAUCONY | `S29101-01` | `S29101-01` | exact match |

Migration `016` accepts either. That one change took the comparison from **641
to 1.054** model-competitor pairs — it had been suppressing matches for every
`ref_prov` seller, not just the new ones. Verified against brand agreement: of
2.536 code matches, the 342 flagged as "different brand" are all naming
variants (`Novedades Nike` vs `NIKE`) with model names in exact agreement.

> **Lesson — when two components apply the "same" rule, test that they agree.**
> The crawler and the view had each been reviewed and each was defensible. The
> bug lived in the gap between them, and it cost 40 % of the matches.

## Phase 11 — Las ocho dimensiones y la serie de posicionamiento

Lo que pidió Forum Sport para el MVP: las ocho dimensiones del dataset como
filtros, y el **POSICIONAMIENTO ONLINE %** (nuestro precio / el del competidor
de referencia) como serie temporal que responda a todos los filtros.

### Los filtros

Siete de las ocho ya estaban en `v_modelos_detalle`; faltaba `custom_label`
(migración 017). Tres más (`cat_extendido`, `abcd_tienda`, `abcd_digital`)
estaban en la vista pero el frontend nunca las pedía.

Están declaradas como **datos, no como ocho bloques repetidos**: cada una es
«elige 1..n valores de una columna», así que la fila de filtros, el predicado y
el botón de limpiar se escriben una vez y recorren `DIMS`. Dos normalizaciones
hacen que los `Set` sean homogéneos: los booleanos pasan a `"true"`/`"false"`, y
`NULL` pasa a un centinela, de modo que «sin clasificación» (294 modelos) es un
valor elegible y no 294 modelos inalcanzables.

Los ocho van detrás de un desplegable «Más filtros»: la barra es `sticky`, y
once desplegables en una fila la convertían en un muro de tres líneas.

### La serie

Objetos nuevos: `precios_fs_diario` (privada, 018) y
`posicionamiento_historico` (pública, 019), más `v_ofertas_emparejadas_diarias`.

> **Lección — un ratio necesita histórico en el numerador, no solo en el
> denominador.** `models.precio_rebaja` es una columna instantánea sin historia.
> Dibujarla contra un denominador que sí se mueve habría recalculado cada punto
> pasado con el precio de *hoy*: cambiar hoy la tarifa de un modelo habría
> reescrito lo que el gráfico dice de marzo. Por eso el crawler fotografía
> nuestro precio cada día, con `on conflict do nothing`: la primera escritura
> del día gana y queda inmutable.

> **Lección — una función de refresco acumulativa no se parece a una
> instantánea.** `refresh_comparativa_publica()` hace `delete ... where true` y
> reconstruye entera: correcto para una foto, catastrófico para un histórico.
> `refresh_posicionamiento_historico()` acota el `delete` a un solo día, porque
> el precio que un competidor tenía un día pasado no se puede reconstruir desde
> ningún sitio.

La agregación diaria se hace **en el navegador**, sobre los mismos objetos que
devuelve `filtered()`. Un RPC habría obligado a escribir el predicado de los
ocho filtros dos veces, en dos lenguajes y sin un test compartido — que es
exactamente la forma de las migraciones 012 y 016. Una coincidencia perdida se
ve; un filtro que discrepa un 3 % es un gráfico verosímil y silenciosamente
falso.

> **Lección — el *carry-forward* va por rival, no por modelo.** La primera
> versión arrastraba «el precio más barato del modelo ese día». Como el crawler
> visita un competidor cada vez, cualquier día en que solo se rastreara un rival
> caro tiraba a la basura otro más barato todavía vigente: el gráfico decía
> 110,8 % donde el KPI decía 112,3 %. Arrastrando cada rival por separado y
> tomando el mínimo después, los dos coinciden al decimal.

**Sesgo de composición.** La cesta cambia de un día a otro (312 modelos el 22 de
septiembre, 571 el 23), así que una media diaria se mueve por cobertura además
de por precio. Se trata con cesta fija sobre la vista, *carry-forward* de 7 días
y el nº de modelos en el tooltip; los días cuya cesta baja del 30 % del máximo
se dibujan **huecos** y no se usan como «último dato». El arreglo correcto a
largo plazo —un índice encadenado de pares emparejados— queda documentado y sin
construir.

**Techo conocido:** por encima de ~40.000 filas en la ventana, la página deja de
pedir el grano completo y baja solo el rival más barato de cada día (lo dice en
la tarjeta). Pasado eso, tocaría mover la serie a un RPC — y entonces sí, con un
test de conformidad que compare los dos caminos.

### El fallo que apareció de paso

Construyendo el histórico salió que **290 de 1.054 parejas (27,5 %) mostraban un
precio de competidor elegido casi al azar**. La clave de colapso era
`coalesce(gtin13, size_raw, '')`, y las ofertas emparejadas por código de
artículo no traen `gtin13` ni casi nunca `size_raw`: para todas ellas la clave
valía la misma cadena vacía, así que `DISTINCT ON` se quedaba con una fila
arbitraria y descartaba el resto **antes** de que `min()` las viera.

Nike publica 125,99 € y 179,99 € en la misma ficha; tres modelos nuestros
comparten `ref_prov HQ3048`, y cuál de los dos precios salía en la página era
una moneda al aire. Entre candidatos la diferencia media era de 24,49 € y la
máxima de 93 €.

La migración 020 hace incolapsables las ofertas sin clave natural (se deduplican
por `id`), de modo que todas llegan al agregado y decide `min()` — que es además
la regla que el proyecto ya tenía escrita: *el precio de referencia es el más
barato encontrado*.

**Efecto en las cifras, dicho claramente:** el posicionamiento medio pasa de
**+7,4 % a +10,3 %** y los modelos en los que ganamos de 34,6 % a 30,7 %.
Estamos peor de lo que la página decía, porque antes nos comparábamos contra un
precio rival a veces más caro de lo real.

> **Lección — un empate en la clave de deduplicación es una decisión tomada a
> cara o cruz.** `DISTINCT ON` siempre devuelve una fila; que sea *la correcta*
> depende de que el `ORDER BY` desempate. Cuando no desempata, no hay error, no
> hay aviso y el número es plausible durante semanas.

### Rastreo diario

`.github/workflows/scrape.yml` tenía la matriz fijada a un competidor de 16 y
no instalaba navegador, así que los tres sitios `headless` habrían fallado.
Ahora son dos jobs —uno HTTP con los quince sitios en serie, otro con navegador
para adidas, Nike y El Corte Inglés— y un fallo individual no tumba el resto.

Un único job secuencial cuesta ~900 min/mes frente a ~1.590 si cada competidor
fuera un job en paralelo, porque Actions factura el arranque de cada runner. El
rastreo en sí son ~29 min/día para todos.

**Sigue pendiente y es el cuello de botella:** los secretos `SUPABASE_URL` y
`SUPABASE_SERVICE_ROLE_KEY` del repositorio. Sin ellos no se ejecuta nada y la
serie se queda donde está.

## Phase 12 — Dynamic Pricing Calculator (not started)

Everything is in place: `margen`, `neto`, `descuento_pct`, `nivel_stock` and
`cobertura_stock` are the levers, and the landing page already frames the
question — **60,2 % of the "muy bajo" stock tier is discounted, against a 55,6 %
catalogue average.** The most-discounted tier is the one with the least to sell.

To decide before building: what a recommended price should optimise (margin,
sell-through, coverage), and whether it is computed in SQL or in the app.
