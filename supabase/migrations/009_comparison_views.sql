-- The unified Forum Sport vs competitors view.
--
-- Grain note: competitor_offers.gtin13 and skus.gtin13 are both per SIZE, so the
-- join is SKU-level. Prices are almost always per model, so the comparison
-- aggregates back up to model grain and keeps the SKU counts as evidence of how
-- much of the size run was actually seen.
--
-- Not granted to anon: see 008. These read competitor tables that stay private.

-- 1. Latest observation per (size, competitor). The append-only history
--    collapses to "current price" here, and nowhere else.
create or replace view v_precio_actual_competencia with (security_invoker = on) as
select distinct on (o.gtin13, o.competitor_slug)
  o.gtin13, o.competitor_slug, o.price, o.list_price, o.currency,
  o.availability, o.promo_text, o.shipping_cost, o.size_raw,
  o.observed_at, o.url
from competitor_offers o
where o.gtin13 is not null
order by o.gtin13, o.competitor_slug, o.observed_at desc;

-- 2. Our price beside theirs, one row per (modelo, competidor).
create or replace view v_comparativa_precios with (security_invoker = on) as
with por_modelo as (
  select
    m.modelo, b.name as marca, m.nombre_modelo, m.tipo_producto,
    m.precio as pvp, m.precio_rebaja as precio_fs, m.descuento_pct,
    m.margen, m.nivel_margen, m.nivel_stock, m.cobertura_stock,
    m.neto, m.url as url_fs, m.img_thumb,
    c.slug as competidor_slug, c.name as competidor, c.classification,
    min(a.price)                                   as precio_comp_min,
    round(avg(a.price), 2)                         as precio_comp_medio,
    max(a.price)                                   as precio_comp_max,
    count(distinct a.gtin13)                       as skus_vistos,
    count(distinct a.gtin13) filter
      (where a.availability ilike '%InStock%')     as skus_disponibles,
    max(a.promo_text)                              as promo,
    max(a.observed_at)                             as observed_at,
    min(a.url)                                     as url_comp
  from v_precio_actual_competencia a
  join skus s        on s.gtin13 = a.gtin13
  join models m      on m.modelo = s.modelo
  join brands b      on b.code   = m.brand_code
  join competitors c on c.slug   = a.competitor_slug
  group by m.modelo, b.name, c.slug, c.name, c.classification
)
select *,
  -- positive = Forum Sport is more expensive than this competitor
  round(precio_fs - precio_comp_min, 2) as delta_eur,
  round((precio_fs - precio_comp_min) / nullif(precio_comp_min, 0) * 100, 2) as delta_pct,
  (precio_fs <= precio_comp_min) as somos_mas_baratos
from por_modelo;

-- 3. Per model: where we stand against the cheapest rival, and — the number the
--    pricing calculator actually needs — what margin would survive matching it.
create or replace view v_posicion_precio with (security_invoker = on) as
with best as (
  select
    modelo,
    min(precio_comp_min)                                  as mejor_precio_comp,
    count(*)                                              as n_competidores,
    count(*) filter (where somos_mas_baratos)             as n_donde_ganamos,
    max(observed_at)                                      as observed_at
  from v_comparativa_precios
  group by modelo
),
cheapest as (
  select distinct on (modelo) modelo, competidor, url_comp
  from v_comparativa_precios
  order by modelo, precio_comp_min, competidor
)
select
  m.modelo, b.name as marca, m.nombre_modelo, m.tipo_producto,
  m.precio as pvp, m.precio_rebaja as precio_fs, m.descuento_pct,
  m.margen, m.nivel_margen, m.nivel_stock, m.nivel_stock_orden, m.cobertura_stock,
  m.neto, m.url as url_fs, m.img_thumb,
  best.mejor_precio_comp, best.n_competidores, best.n_donde_ganamos,
  ch.competidor as competidor_mas_barato, ch.url_comp,
  round(m.precio_rebaja - best.mejor_precio_comp, 2) as gap_eur,
  round((m.precio_rebaja - best.mejor_precio_comp)
        / nullif(best.mejor_precio_comp, 0) * 100, 2) as gap_pct,
  case
    when m.precio_rebaja < best.mejor_precio_comp then 'más barato'
    when m.precio_rebaja = best.mejor_precio_comp then 'igual'
    else 'más caro'
  end as posicion,
  -- neto is our cost floor (precio_rebaja * (1 - margen)). Matching the cheapest
  -- rival is only worth doing while this stays acceptable — and on a "muy bajo"
  -- margin model there is almost no room, which is the whole point.
  round((best.mejor_precio_comp - m.neto)
        / nullif(best.mejor_precio_comp, 0), 4)        as margen_si_igualamos,
  (best.mejor_precio_comp <= m.neto)                   as igualar_da_perdidas,
  best.observed_at
from models m
join best   on best.modelo = m.modelo
join cheapest ch on ch.modelo = m.modelo
join brands b on b.code = m.brand_code;

-- 4. Coverage: how much of the catalogue each competitor actually carries.
create or replace view v_cobertura_competencia with (security_invoker = on) as
select
  c.slug, c.name as competidor, c.classification, c.enabled,
  count(distinct v.modelo)                                       as modelos_encontrados,
  round(100.0 * count(distinct v.modelo) / 1483.0, 1)            as pct_catalogo,
  count(distinct v.modelo) filter (where v.somos_mas_baratos)    as modelos_donde_ganamos,
  round(avg(v.delta_pct), 2)                                     as delta_medio_pct,
  max(v.observed_at)                                             as ultima_observacion
from competitors c
left join v_comparativa_precios v on v.competidor_slug = c.slug
group by c.slug, c.name, c.classification, c.enabled;
