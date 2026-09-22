-- A second matching path, for retailers that publish no GTIN.
--
-- The EAN join carried everything so far because Atmósfera publishes gtin13.
-- adidas does not: their JSON-LD ProductGroup carries sizes and prices but no
-- gtin at all. What they do expose is the article code, both as the last path
-- segment of the product URL (/zapatilla-galaxy-6/GW4139.html) and in the page.
--
-- That code is exactly what our catalogue stores as models.ref_prov: 230 of our
-- 231 adidas models match the ^[A-Z]{2}[0-9]{4,5}$ article-code shape, and 66
-- of them appear verbatim in adidas's own product sitemap.
--
-- So offers now match on either key, and every matched offer records WHICH key
-- was used — a price matched by article code is a model-level match, while a
-- GTIN match is size-exact, and the two should never be silently conflated.

create or replace view v_ofertas_emparejadas with (security_invoker = on) as
-- 1. GTIN path: size-exact.
select
  o.id, o.competitor_slug, o.product_id, o.observed_at, o.gtin13, o.mpn,
  o.size_raw, o.price, o.list_price, o.currency, o.availability,
  o.promo_text, o.shipping_cost, o.url,
  s.modelo,
  'gtin13'::text as match_method
from competitor_offers o
join skus s on s.gtin13 = o.gtin13
where o.gtin13 is not null

union all

-- 2. Article-code path: model-level, for sellers that publish no GTIN.
select
  o.id, o.competitor_slug, o.product_id, o.observed_at, o.gtin13, o.mpn,
  o.size_raw, o.price, o.list_price, o.currency, o.availability,
  o.promo_text, o.shipping_cost, o.url,
  m.modelo,
  'ref_prov'::text
from competitor_offers o
join models m on upper(m.ref_prov) = upper(o.mpn)
where o.gtin13 is null and o.mpn is not null;

comment on view v_ofertas_emparejadas is
  'Offers joined to our catalogue by GTIN-13 (size-exact) or article code (model-level). match_method says which.';

-- Rebuild the comparison on top of both paths.
create or replace view v_comparativa_precios with (security_invoker = on) as
with latest as (
  select distinct on (e.modelo, e.competitor_slug, coalesce(e.gtin13, e.size_raw, ''))
    e.modelo, e.competitor_slug, e.gtin13, e.size_raw, e.price, e.availability,
    e.promo_text, e.observed_at, e.url, e.match_method
  from v_ofertas_emparejadas e
  order by e.modelo, e.competitor_slug, coalesce(e.gtin13, e.size_raw, ''), e.observed_at desc
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
