-- A narrow, public slice of the competitor comparison, for the landing page.
--
-- The rich views (v_posicion_precio, v_comparativa_precios) stay private: they
-- carry margen, neto, cobertura_stock and margen_si_igualamos — the pricing
-- strategy, which is exactly what a rival would want to read.
--
-- Why a TABLE and not a view: a view over the private competitor tables would
-- have to be SECURITY DEFINER to bypass their RLS, which Supabase's linter
-- flags as an ERROR and rightly so — it is a standing hole that reads whatever
-- the definition happens to select. A table refreshed by the scraper needs no
-- privilege escalation at all: the service_role writes it, anon reads it under
-- an ordinary policy, and the column list is fixed at write time.
--
-- It also makes the landing page cheaper: one small table instead of a join
-- across the whole offer history on every page load.

drop view if exists v_comparativa_publica;

create table if not exists comparativa_publica (
  modelo           bigint primary key references models(modelo) on delete cascade,
  marca            text not null,
  nombre_modelo    text not null,
  tipo_producto    text not null,
  img_thumb        text,
  url_fs           text,
  pvp              numeric(10,2),
  precio_fs        numeric(10,2),
  nivel_stock      text,
  competidor       text not null,
  precio_comp      numeric(10,2) not null,
  url_comp         text,
  skus_vistos      integer,
  skus_disponibles integer,
  promo            text,
  delta_eur        numeric(10,2),
  delta_pct        numeric(10,2),
  somos_mas_baratos boolean,
  observed_at      timestamptz
);

comment on table comparativa_publica is
  'Public price comparison for the landing page, refreshed by the scraper. Margin, cost and stock-coverage are deliberately absent — the column list is the security boundary.';

-- Rebuilt after every crawl. Keeps the cheapest observed rival per model.
create or replace function refresh_comparativa_publica() returns integer as $$
declare n integer;
begin
  delete from comparativa_publica;
  insert into comparativa_publica
  select distinct on (v.modelo)
    v.modelo, v.marca, v.nombre_modelo, v.tipo_producto, v.img_thumb, v.url_fs,
    v.pvp, v.precio_fs, v.nivel_stock, v.competidor, v.precio_comp_min, v.url_comp,
    v.skus_vistos, v.skus_disponibles, v.promo,
    v.delta_eur, v.delta_pct, v.somos_mas_baratos, v.observed_at
  from v_comparativa_precios v
  order by v.modelo, v.precio_comp_min asc;
  get diagnostics n = row_count;
  return n;
end;
$$ language plpgsql
  -- Pinned: without it a caller could shadow `models`/`skus` via their own
  -- search_path and make this function read different tables than intended.
  set search_path = public;

-- Only the service_role (the scraper) may rebuild it.
revoke all on function refresh_comparativa_publica() from public, anon, authenticated;

alter table comparativa_publica enable row level security;

drop policy if exists "comparison is publicly readable" on comparativa_publica;
create policy "comparison is publicly readable"
  on comparativa_publica for select to anon, authenticated using (true);

revoke all on comparativa_publica from anon, authenticated;
grant select on comparativa_publica to anon, authenticated;
