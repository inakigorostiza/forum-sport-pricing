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
| 7 | Landing page de visualización | Done |
| 8 | GitHub + despliegue en Vercel | Done |
| 9 | Dynamic Pricing Calculator | Not started |

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

### 7.5 Product images, reverse-engineered

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

## Phase 9 — Dynamic Pricing Calculator (not started)

Everything is in place: `margen`, `neto`, `descuento_pct`, `nivel_stock` and
`cobertura_stock` are the levers, and the landing page already frames the
question — **60,2 % of the "muy bajo" stock tier is discounted, against a 55,6 %
catalogue average.** The most-discounted tier is the one with the least to sell.

To decide before building: what a recommended price should optimise (margin,
sell-through, coverage), and whether it is computed in SQL or in the app.
