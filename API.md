# Forum Sport pricing API

REST endpoints for the landing page. Every call below was executed against the
live project and returned the data shown — see `scripts/verify_api.sh`.

| | |
|---|---|
| Project | `forum-sport-pricing` (`hhehxwdpvoojgjbogton`) |
| Base URL | `https://hhehxwdpvoojgjbogton.supabase.co` |
| Region | `eu-west-3` (Paris) · Postgres 17.6 |
| Data | 1.483 models · 24.109 SKUs · 28 brands |

## Keys

| Key | Use | Safe in a browser? |
|---|---|---|
| `anon` / publishable | the landing page | **yes** — RLS restricts it to reads |
| `service_role` | loaders, server-side jobs | **no** — bypasses RLS entirely |

```
SUPABASE_URL=https://hhehxwdpvoojgjbogton.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhoZWh4d2Rwdm9vamdqYm9ndG9uIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwNzI0MTgsImV4cCI6MjEwNTY0ODQxOH0.JzAvwowqBm6hFM9Ct19Tqq-MyxROK-JAiYjg7LWaROY
```

The `anon` key is designed to be public. Access is restricted by Row Level
Security (read-only) *and* by table privileges (`SELECT` only) — both layers.

## Setup

```bash
npm install @supabase/supabase-js
```

```js
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)
```

## Views — one per visualization

Each returns a small, pre-aggregated result. Prefer these over fetching 1.483
models and aggregating in the browser.

| View | Rows | Use for |
|---|---|---|
| `v_kpis` | 1 | headline figures |
| `v_por_marca` | 28 | brand comparison |
| `v_por_nivel_margen` | 4 | margin distribution |
| `v_por_nivel_stock` | 5 | stock distribution |
| `v_por_temporada` | ~15 | season × year |
| `v_abcd_matriz` | ~30 | store vs digital classification |
| `v_por_tipo_producto` | 2 | running vs trail |
| `v_bandas_precio` | 9 | price histogram |
| `v_curva_tallas` | 20 | size curve |
| `v_modelos_detalle` | 1.483 | the model listing |

Views ending in a level (`nivel_margen`, `nivel_stock`, `banda`) also return a
`*_orden` integer. **Sort on that**, not on the label — `muy bajo … muy alto`
does not sort alphabetically.

### `v_kpis`

```js
const { data } = await supabase.from('v_kpis').select('*').single()
```

```json
{ "total_modelos": 1483, "total_skus": 24109, "total_marcas": 28,
  "total_nombres_modelo": 646, "precio_medio": 145.59,
  "precio_rebaja_medio": 123.12, "modelos_en_rebaja": 824,
  "pct_en_rebaja": 55.56, "descuento_medio_pct": 27.43,
  "margen_medio": 0.2759, "modelos_outlet": 112,
  "modelos_exclusivo_online": 682 }
```

### `v_por_marca`

```js
const { data } = await supabase
  .from('v_por_marca').select('*').order('modelos', { ascending: false })
```

```json
[{ "marca_codigo": "NIKE", "marca": "NIKE", "modelos": 239, "skus": 4070,
   "precio_medio": 143.82, "modelos_en_rebaja": 140,
   "descuento_medio_pct": 27.01, "margen_medio": 0.2469 }]
```

Averages are at **model grain** — a model counts once regardless of how many
sizes it has.

### `v_por_nivel_margen` / `v_por_nivel_stock`

```js
const { data } = await supabase
  .from('v_por_nivel_margen').select('*').order('nivel_margen_orden')
```

```json
[{ "nivel_margen": "muy bajo", "nivel_margen_orden": 1, "margen": 0.150, "modelos": 287, "pct": 19.35 },
 { "nivel_margen": "bajo",     "nivel_margen_orden": 2, "margen": 0.200, "modelos": 261, "pct": 17.60 },
 { "nivel_margen": "medio",    "nivel_margen_orden": 3, "margen": 0.300, "modelos": 601, "pct": 40.53 },
 { "nivel_margen": "alto",     "nivel_margen_orden": 4, "margen": 0.400, "modelos": 334, "pct": 22.52 }]
```

### `v_bandas_precio`

```js
const { data } = await supabase.from('v_bandas_precio').select('*').order('banda_orden')
```

## Tables

### Top discounts

```js
const { data } = await supabase
  .from('models')
  .select('modelo,nombre_modelo,precio,precio_rebaja,descuento_pct,url')
  .eq('en_rebaja', true)
  .order('descuento_pct', { ascending: false })
  .limit(10)
```

```json
[{ "modelo": 1001071778, "nombre_modelo": "GORBEA", "precio": "140.00",
   "precio_rebaja": "70.00", "descuento_pct": "50.00",
   "url": "https://www.forumsport.com/es-es/-1001071778-p" }]
```

### One model with its sizes (embedded join)

```js
const { data } = await supabase
  .from('models').select('*, skus(talla, talla_es, ean)')
  .eq('modelo', 1001142170).single()
```

### Filtering the listing

```js
let q = supabase.from('v_modelos_detalle').select('*')
q = q.eq('brand_code', 'NIKE')            // note: brand_code, not marca_codigo
q = q.eq('tipo_producto', 'zapatillas trail hombre')
q = q.eq('nivel_stock', 'muy bajo')
q = q.gte('precio', 100).lte('precio', 200)
q = q.eq('en_rebaja', true)
const { data } = await q.order('descuento_pct', { ascending: false }).limit(50)
```

### Pagination

PostgREST caps responses at 1.000 rows. For all 1.483 models, page:

```js
const { data, count } = await supabase
  .from('v_modelos_detalle').select('*', { count: 'exact' }).range(0, 999)
```

## Computed fields

These are generated columns — computed in Postgres, never in the frontend.

| Field | Definition |
|---|---|
| `neto` | `precio_rebaja × (1 − margen)` — the source's `NETO SINTÉTICO*` |
| `descuento_pct` | `(precio − precio_rebaja) / precio × 100` |
| `en_rebaja` | `precio_rebaja < precio` |
| `url` | public product page on forumsport.com |
| `img_thumb` / `img_full` | product shot, 200×200 / 1000×1000 |
| `nivel_margen_orden`, `nivel_stock_orden` | 1–5, for sorting |

## Product images

`models.img_thumb` (200×200) and `img_full` (1000×1000) are generated columns.
The CDN pattern is:

```
https://www.forumsport.com/images/{slug}-lateral-exterior-{modelo}-{size}-f
```

Verified against the live CDN:

- **The slug is decorative.** A deliberately wrong slug returns the
  byte-identical image — resolution depends only on `{modelo}`.
- **`lateral-exterior` is required.** Drop it and the CDN answers `200` with a
  **zero-byte body**, not a 404.
- **Only `200x200`, `500x500` and `1000x1000` exist.** Every other size also
  answers `200` with 0 bytes, so a wrong size fails *silently*. Always render
  with an `onerror` fallback.
- Coverage: 26 models sampled across the 12 largest brands, 26/26 had an image.
  No hotlink protection — they load cross-origin from a browser.

```js
const { data } = await supabase
  .from('v_modelos_detalle')
  .select('modelo,nombre_modelo,marca,precio_rebaja,img_thumb')
  .order('descuento_pct', { ascending: false }).limit(12)
```

```html
<img src="${m.img_thumb}" alt="" loading="lazy" width="46" height="46"
     onerror="this.removeAttribute('src')">
```

## Gotchas

- **`numeric` arrives as a string** in JSON (`"140.00"`). Use `Number(x)` before
  arithmetic or charting.
- **`ano_temporada = 9998`** is a "year unknown" sentinel, not a year (2 models).
  `v_por_temporada` exposes `ano_desconocido` so you can exclude it from axes.
- **`cobertura_stock` is `null`** for 249 models ("SIN DATOS COBERTURA" in the
  source). Distinguish "no data" from zero coverage.
- **7 SKUs have `talla_es = 0`** — an unmapped size in the source.
- **`brand_code` vs `marca_codigo`**: `v_modelos_detalle` exposes `brand_code`;
  `v_por_marca` exposes `marca_codigo`.

## Security

Writes are rejected for anonymous callers at two independent layers: table
privileges (`SELECT` only) and RLS (no write policies). Verified by
`scripts/verify_api.sh`, which attempts `POST`, `PATCH` and `DELETE` and then
re-reads the data to confirm nothing changed.

```
PASS  POST   brands   rejected [401]
PASS  DELETE skus     rejected [401]
PASS  PATCH  models   rejected [401]
PASS  total_skus 24109 · targeted sku present · precio still 140.00
```
