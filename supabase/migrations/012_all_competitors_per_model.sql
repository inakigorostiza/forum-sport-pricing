-- Keep every (model, competitor) pair in the public table.
--
-- refresh_comparativa_publica() used `distinct on (modelo)` and kept only the
-- cheapest rival, which silently discarded the other prices: with three
-- competitors crawled, 4 models had a second price that never reached the page.
-- For price monitoring that is the wrong default — seeing that two rivals sit
-- at different prices is the point.
--
-- The primary key therefore becomes (modelo, competidor).

alter table comparativa_publica drop constraint if exists comparativa_publica_pkey;
alter table comparativa_publica add primary key (modelo, competidor);

create or replace function refresh_comparativa_publica() returns integer as $$
declare n integer;
begin
  delete from comparativa_publica where true;
  insert into comparativa_publica
  select
    v.modelo, v.marca, v.nombre_modelo, v.tipo_producto, v.img_thumb, v.url_fs,
    v.pvp, v.precio_fs, v.nivel_stock, v.competidor, v.precio_comp_min, v.url_comp,
    v.skus_vistos, v.skus_disponibles, v.promo,
    v.delta_eur, v.delta_pct, v.somos_mas_baratos, v.observed_at
  from v_comparativa_precios v;
  get diagnostics n = row_count;
  return n;
end;
$$ language plpgsql
  set search_path = public;

revoke all on function refresh_comparativa_publica() from public, anon, authenticated;

select refresh_comparativa_publica() as filas;
