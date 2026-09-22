-- Reporting views for the landing page: one view per visualization, so the
-- frontend makes a single request per chart instead of pulling 1.483 models
-- and aggregating in the browser.
--
-- All views are security_invoker, so the RLS policies of the underlying
-- tables apply to the caller rather than to the view owner.

-- 1. Headline KPIs (single row) -----------------------------------------
create or replace view v_kpis with (security_invoker = on) as
select
  (select count(*) from models)                         as total_modelos,
  (select count(*) from skus)                           as total_skus,
  (select count(*) from brands)                         as total_marcas,
  (select count(distinct nombre_modelo) from models)    as total_nombres_modelo,
  (select round(avg(precio), 2)        from models)     as precio_medio,
  (select round(avg(precio_rebaja), 2) from models)     as precio_rebaja_medio,
  (select count(*) from models where en_rebaja)         as modelos_en_rebaja,
  (select round(100.0 * count(*) filter (where en_rebaja) / count(*), 2)
     from models)                                       as pct_en_rebaja,
  (select round(avg(descuento_pct), 2)
     from models where en_rebaja)                       as descuento_medio_pct,
  (select round(avg(margen), 4) from models)            as margen_medio,
  (select count(*) from models where outlet)            as modelos_outlet,
  (select count(*) from models where exclusivo_online)  as modelos_exclusivo_online;

-- 2. Per brand -----------------------------------------------------------
-- SKU counts are computed separately so the price averages stay at model
-- grain (a join to skus would weight every model by its number of sizes).
create or replace view v_por_marca with (security_invoker = on) as
with sku_counts as (
  select m.brand_code, count(*)::bigint as skus
  from skus s
  join models m on m.modelo = s.modelo
  group by m.brand_code
)
select
  b.code                                                   as marca_codigo,
  b.name                                                   as marca,
  count(m.modelo)::bigint                                  as modelos,
  coalesce(sc.skus, 0)                                     as skus,
  round(avg(m.precio), 2)                                  as precio_medio,
  round(avg(m.precio_rebaja), 2)                           as precio_rebaja_medio,
  min(m.precio)                                            as precio_min,
  max(m.precio)                                            as precio_max,
  count(*) filter (where m.en_rebaja)::bigint              as modelos_en_rebaja,
  round(avg(m.descuento_pct) filter (where m.en_rebaja), 2) as descuento_medio_pct,
  round(avg(m.margen), 4)                                  as margen_medio,
  count(*) filter (where m.outlet)::bigint                 as modelos_outlet,
  count(*) filter (where m.exclusivo_online)::bigint       as modelos_exclusivo_online
from brands b
join models m on m.brand_code = b.code
left join sku_counts sc on sc.brand_code = b.code
group by b.code, b.name, sc.skus;

-- 3. Margin-level distribution -------------------------------------------
create or replace view v_por_nivel_margen with (security_invoker = on) as
select
  nivel_margen,
  nivel_margen_orden,
  margen,
  count(*)::bigint                                    as modelos,
  round(100.0 * count(*) / sum(count(*)) over (), 2)  as pct
from models
group by nivel_margen, nivel_margen_orden, margen
order by nivel_margen_orden;

-- 4. Stock-level distribution --------------------------------------------
create or replace view v_por_nivel_stock with (security_invoker = on) as
select
  nivel_stock,
  nivel_stock_orden,
  count(*)::bigint                                    as modelos,
  round(100.0 * count(*) / sum(count(*)) over (), 2)  as pct,
  round(avg(cobertura_stock), 1)                      as cobertura_media,
  count(*) filter (where cobertura_stock is null)::bigint as sin_datos_cobertura
from models
group by nivel_stock, nivel_stock_orden
order by nivel_stock_orden;

-- 5. Season × year matrix (long format; the frontend pivots) --------------
create or replace view v_por_temporada with (security_invoker = on) as
select
  temporada,
  ano_temporada,
  (ano_temporada = 9998)   as ano_desconocido,
  count(*)::bigint         as modelos
from models
group by temporada, ano_temporada
order by temporada, ano_temporada;

-- 6. ABCD store × digital cross-tab --------------------------------------
create or replace view v_abcd_matriz with (security_invoker = on) as
select
  coalesce(abcd_tienda,  'SIN DATOS') as abcd_tienda,
  coalesce(abcd_digital, 'SIN DATOS') as abcd_digital,
  count(*)::bigint                    as modelos
from models
group by 1, 2
order by 1, 2;

-- 7. Product type ---------------------------------------------------------
create or replace view v_por_tipo_producto with (security_invoker = on) as
with sku_counts as (
  select m.tipo_producto, count(*)::bigint as skus
  from skus s join models m on m.modelo = s.modelo
  group by m.tipo_producto
)
select
  m.tipo_producto,
  count(*)::bigint              as modelos,
  coalesce(sc.skus, 0)          as skus,
  round(avg(m.precio), 2)       as precio_medio,
  round(avg(m.margen), 4)       as margen_medio
from models m
left join sku_counts sc on sc.tipo_producto = m.tipo_producto
group by m.tipo_producto, sc.skus
order by modelos desc;

-- 8. Price-band histogram -------------------------------------------------
create or replace view v_bandas_precio with (security_invoker = on) as
select
  case
    when precio <  60 then '< 60 €'
    when precio <  80 then '60 - 79 €'
    when precio < 100 then '80 - 99 €'
    when precio < 120 then '100 - 119 €'
    when precio < 140 then '120 - 139 €'
    when precio < 160 then '140 - 159 €'
    when precio < 180 then '160 - 179 €'
    when precio < 200 then '180 - 199 €'
    else                   '200 € o más'
  end as banda,
  case
    when precio <  60 then 1 when precio <  80 then 2
    when precio < 100 then 3 when precio < 120 then 4
    when precio < 140 then 5 when precio < 160 then 6
    when precio < 180 then 7 when precio < 200 then 8
    else                   9
  end::smallint                               as banda_orden,
  count(*)::bigint                            as modelos,
  count(*) filter (where en_rebaja)::bigint   as modelos_en_rebaja,
  round(avg(margen), 4)                       as margen_medio
from models
group by banda, banda_orden
order by banda_orden;

-- 9. Size curve -----------------------------------------------------------
create or replace view v_curva_tallas with (security_invoker = on) as
select
  talla_es,
  count(*)::bigint                  as skus,
  count(distinct modelo)::bigint    as modelos
from skus
group by talla_es
order by talla_es;

-- 10. Main model listing --------------------------------------------------
create or replace view v_modelos_detalle with (security_invoker = on) as
select
  m.modelo,
  m.brand_code,
  b.name                    as marca,
  m.nombre_modelo,
  m.color,
  m.tipo_producto,
  m.temporada,
  m.ano_temporada,
  m.precio,
  m.precio_rebaja,
  m.descuento_pct,
  m.en_rebaja,
  m.neto,
  m.margen,
  m.nivel_margen,
  m.nivel_margen_orden,
  m.cobertura_stock,
  m.nivel_stock,
  m.nivel_stock_orden,
  m.outlet,
  m.exclusivo_online,
  m.cat_extendido,
  m.abcd_tienda,
  m.abcd_digital,
  m.url,
  count(s.material)::bigint as num_skus,
  min(s.talla_es)           as talla_es_min,
  max(s.talla_es)           as talla_es_max
from models m
join brands b on b.code = m.brand_code
left join skus s on s.modelo = m.modelo
group by m.modelo, b.name;

grant select on
  v_kpis, v_por_marca, v_por_nivel_margen, v_por_nivel_stock,
  v_por_temporada, v_abcd_matriz, v_por_tipo_producto,
  v_bandas_precio, v_curva_tallas, v_modelos_detalle
to anon, authenticated;
