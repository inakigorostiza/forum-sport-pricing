-- Stop picking an arbitrary price when several offers share a model.
--
-- Found while building the daily history: 290 of 1.054 (modelo, competidor)
-- pairs showed a price chosen essentially at random.
--
-- The collapse key was coalesce(gtin13, size_raw, ''). Offers matched by
-- article code carry NO gtin13 and often no size_raw, so for every one of them
-- the key evaluated to the same empty string. DISTINCT ON then kept exactly one
-- row per (modelo, competidor) and discarded the rest before min() ever saw
-- them -- and with identical observed_at the survivor is arbitrary.
--
-- Concretely: Nike product 311 publishes 125,99 EUR and 179,99 EUR on one page
-- (list and sale). Three of our models share ref_prov HQ3048, so both offers
-- matched all three, and which price the page displayed was a coin flip. Across
-- the catalogue the two candidates differed by 24,49 EUR on average and by as
-- much as 93 EUR.
--
-- The fix is to make keyless offers un-collapsible: dedupe on the offer id when
-- there is no natural key, so every distinct offer survives into the aggregate
-- and min() decides. That is also the rule the rest of the project already
-- states -- the reference competitor price is the cheapest one found -- so this
-- makes the view agree with its own documentation.
--
-- Effect on the figures: a competitor price can only move DOWN or stay equal,
-- because an arbitrary pick is replaced by the minimum. Our position therefore
-- looks slightly worse, and more honestly so.
create or replace view v_comparativa_precios with (security_invoker = on) as
with latest as (
  select distinct on (e.modelo, e.competitor_slug,
                      coalesce(e.gtin13, e.size_raw, e.id::text))
    e.modelo, e.competitor_slug, e.gtin13, e.size_raw, e.price, e.availability,
    e.promo_text, e.observed_at, e.url, e.match_method
  from v_ofertas_emparejadas e
  order by e.modelo, e.competitor_slug,
           coalesce(e.gtin13, e.size_raw, e.id::text), e.observed_at desc
),
por_modelo as (
  select
    m.modelo, b.name as marca, m.nombre_modelo, m.tipo_producto,
    m.precio as pvp, m.precio_rebaja as precio_fs, m.descuento_pct,
    m.margen, m.nivel_margen, m.nivel_stock, m.cobertura_stock,
    m.neto, m.url as url_fs, m.img_thumb,
    c.slug as competidor_slug, c.name as competidor, c.classification,
    min(l.price)                                   as precio_comp_min,
    round(avg(l.price), 2)                         as precio_comp_medio,
    max(l.price)                                   as precio_comp_max,
    count(*)                                       as skus_vistos,
    count(*) filter (where l.availability ilike '%InStock%') as skus_disponibles,
    max(l.promo_text)                              as promo,
    max(l.observed_at)                             as observed_at,
    min(l.url)                                     as url_comp,
    min(l.match_method)                            as match_method
  from latest l
  join models m      on m.modelo = l.modelo
  join brands b      on b.code   = m.brand_code
  join competitors c on c.slug   = l.competitor_slug
  group by m.modelo, b.name, c.slug, c.name, c.classification
)
select *,
  round(precio_fs - precio_comp_min, 2) as delta_eur,
  round((precio_fs - precio_comp_min) / nullif(precio_comp_min, 0) * 100, 2) as delta_pct,
  (precio_fs <= precio_comp_min) as somos_mas_baratos
from por_modelo;

-- The daily view must collapse by the same rule, or a chart point would not
-- equal the same day's KPI row.
create or replace view v_ofertas_emparejadas_diarias
  with (security_invoker = on) as
with ult as (
  select distinct on (
      (e.observed_at at time zone 'Europe/Madrid')::date,
      e.modelo, e.competitor_slug, coalesce(e.gtin13, e.size_raw, e.id::text))
    (e.observed_at at time zone 'Europe/Madrid')::date as fecha,
    e.modelo, e.competitor_slug, e.price, e.observed_at
  from v_ofertas_emparejadas e
  order by
    (e.observed_at at time zone 'Europe/Madrid')::date,
    e.modelo, e.competitor_slug, coalesce(e.gtin13, e.size_raw, e.id::text),
    e.observed_at desc
)
select
  u.fecha, u.modelo, u.competitor_slug,
  min(u.price)        as precio_comp,
  count(*)::integer   as skus_vistos,
  max(u.observed_at)  as observed_at
from ult u
group by u.fecha, u.modelo, u.competitor_slug;
