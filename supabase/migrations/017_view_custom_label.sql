-- Expose custom_label to the landing page.
--
-- Forum Sport asked for eight catalogue dimensions as filters. Seven were
-- already on this view; custom_label was the only one missing, so the browser
-- had no way to filter on it.
--
-- CREATE OR REPLACE VIEW only permits adding columns at the end, which means
-- restating the whole select. The definition being extended is the one in
-- 006_view_images.sql, not 003_views.sql — 006 replaced it.
create or replace view v_modelos_detalle with (security_invoker = on) as
select
  m.modelo, m.brand_code, b.name as marca, m.nombre_modelo, m.color,
  m.tipo_producto, m.temporada, m.ano_temporada,
  m.precio, m.precio_rebaja, m.descuento_pct, m.en_rebaja, m.neto,
  m.margen, m.nivel_margen, m.nivel_margen_orden,
  m.cobertura_stock, m.nivel_stock, m.nivel_stock_orden,
  m.outlet, m.exclusivo_online, m.cat_extendido,
  m.abcd_tienda, m.abcd_digital, m.url,
  count(s.material)::bigint as num_skus,
  min(s.talla_es)           as talla_es_min,
  max(s.talla_es)           as talla_es_max,
  m.img_thumb,
  m.img_full,
  -- '' in the source becomes NULL here, which the UI offers as "Sin etiqueta"
  -- rather than hiding those 183 models.
  m.custom_label
from models m
join brands b on b.code = m.brand_code
left join skus s on s.modelo = m.modelo
group by m.modelo, b.name;

grant select on v_modelos_detalle to anon, authenticated;
