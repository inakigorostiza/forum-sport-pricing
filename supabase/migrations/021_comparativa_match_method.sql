-- Carry the match method onto the public comparison.
--
-- The pricing engine scores how much to trust each recommendation, and the
-- single biggest driver is how the competitor price was matched: a gtin13 match
-- is size-exact, a ref_prov match is model-level and can pair our colourway
-- with a different one of theirs. v_comparativa_precios has computed it since
-- 011, but comparativa_publica never carried it, so the browser could not tell
-- the two apart.
alter table comparativa_publica
  add column if not exists match_method text;

comment on column comparativa_publica.match_method is
  'gtin13 = size-exact match; ref_prov = model-level match via the article code. Feeds the confidence score of the price recommendation.';

create or replace function refresh_comparativa_publica() returns integer as $$
declare n integer;
begin
  delete from comparativa_publica where true;
  insert into comparativa_publica
  select
    v.modelo, v.marca, v.nombre_modelo, v.tipo_producto, v.img_thumb, v.url_fs,
    v.pvp, v.precio_fs, v.nivel_stock, v.competidor, v.precio_comp_min, v.url_comp,
    v.skus_vistos, v.skus_disponibles, v.promo,
    v.delta_eur, v.delta_pct, v.somos_mas_baratos, v.observed_at,
    v.match_method
  from v_comparativa_precios v;
  get diagnostics n = row_count;
  return n;
end;
$$ language plpgsql
  set search_path = public;
