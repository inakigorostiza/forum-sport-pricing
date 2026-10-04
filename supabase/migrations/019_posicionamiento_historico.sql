-- POSICIONAMIENTO ONLINE % over time: comparativa_publica with the time
-- dimension put back.
--
-- Forum Sport's metric is (our price / reference competitor price) x 100, over
-- an arbitrary period, responding to every filter on the page. comparativa_publica
-- cannot answer it: it is a destructively rebuilt snapshot with no date column.
-- The only price history in the system is competitor_offers (append-only), and
-- everything downstream of v_ofertas_emparejadas collapses it to "latest".

-- ── 1. One competitor price per model per day ────────────────────────────
--
-- This MUST mirror v_comparativa_precios (011) in both steps, or a point on the
-- chart will not equal the same day's KPI row and nobody will notice for weeks:
--   a) within the day, take the LATEST observation per (gtin13|size, competitor)
--   b) then take min(price) across the model's SKUs  [= precio_comp_min]
--
-- The date is pinned to Europe/Madrid. A bare ::date on a timestamptz resolves
-- against the server TimeZone, which is UTC on Supabase: a manual crawl at 23:30
-- Madrid would land on the following day and split one crawl across two points.
create or replace view v_ofertas_emparejadas_diarias
  with (security_invoker = on) as
with ult as (
  select distinct on (
      (e.observed_at at time zone 'Europe/Madrid')::date,
      e.modelo, e.competitor_slug, coalesce(e.gtin13, e.size_raw, ''))
    (e.observed_at at time zone 'Europe/Madrid')::date as fecha,
    e.modelo, e.competitor_slug, e.price, e.observed_at
  from v_ofertas_emparejadas e
  order by
    (e.observed_at at time zone 'Europe/Madrid')::date,
    e.modelo, e.competitor_slug, coalesce(e.gtin13, e.size_raw, ''),
    e.observed_at desc
)
select
  u.fecha, u.modelo, u.competitor_slug,
  min(u.price)        as precio_comp,
  count(*)::integer   as skus_vistos,
  max(u.observed_at)  as observed_at
from ult u
group by u.fecha, u.modelo, u.competitor_slug;

comment on view v_ofertas_emparejadas_diarias is
  'One competitor price per (day, model, competitor), collapsed with the same rule as v_comparativa_precios.';

-- ── 2. The public, chart-facing history ──────────────────────────────────
--
-- A table written by service_role, not a SECURITY DEFINER view over the
-- RLS-protected competitor tables — the Supabase linter flags that as ERROR.
-- Same pattern and same reasoning as 010.
create table if not exists posicionamiento_historico (
  fecha           date           not null,
  modelo          bigint         not null references models(modelo) on delete cascade,
  -- Both the slug and the display name. The slug is the stable key; the name is
  -- what the page's competitor filter actually holds (it builds its options from
  -- comparativa_publica.competidor), so a slug-only table would silently match
  -- nothing the moment a user picks a competitor.
  competidor      text           not null,
  competidor_slug text           not null references competitors(slug) on delete cascade,
  precio_fs       numeric(10,2),            -- NULL = our price that day is unknown
  precio_comp     numeric(10,2)  not null,
  posicionamiento numeric(6,2),             -- precio_fs / precio_comp * 100; NULL iff precio_fs is
  es_mas_barato   boolean        not null,  -- cheapest rival for this (fecha, modelo)
  skus_vistos     integer,
  observed_at     timestamptz    not null,
  primary key (fecha, modelo, competidor_slug)
);

comment on table posicionamiento_historico is
  'Daily POSICIONAMIENTO ONLINE %, one row per (day, model, competitor). Accumulates; never rebuilt wholesale.';
comment on column posicionamiento_historico.es_mas_barato is
  'Fetch selector only, never a computation: it decides which rows the page downloads, not what it computes. The page always recomputes min() over whatever arrived, so this flag cannot diverge from its logic.';
comment on column posicionamiento_historico.precio_fs is
  'NULL means we did not know our own price that day, not that it was zero.';

create index if not exists idx_hist_fecha_barato
  on posicionamiento_historico (fecha) where es_mas_barato;
create index if not exists idx_hist_comp_fecha
  on posicionamiento_historico (competidor_slug, fecha);

alter table posicionamiento_historico enable row level security;

drop policy if exists "history is publicly readable" on posicionamiento_historico;
create policy "history is publicly readable"
  on posicionamiento_historico for select to anon, authenticated using (true);

revoke all on posicionamiento_historico from anon, authenticated;
grant select on posicionamiento_historico to anon, authenticated;

-- ── 3. The refresh ──────────────────────────────────────────────────────
--
-- Deliberately NOT shaped like refresh_comparativa_publica(). That one does
-- "delete from comparativa_publica where true" — a full destructive rebuild,
-- which is correct for a snapshot and catastrophic for an accumulating table:
-- one bad deploy would erase history that cannot be reconstructed, because
-- nobody stores competitor prices for past days. The delete here is scoped to
-- the single day being rewritten.
--
-- Scoped delete-then-insert also makes it idempotent, which matters because
-- four crawler entry points call it (run.py, run_nike.py, run_adidas.py,
-- run_salomon.py). Whichever runs last produces the complete picture for the
-- day, regardless of order or how many ran.
create or replace function refresh_posicionamiento_historico(
  p_fecha date default (now() at time zone 'Europe/Madrid')::date
) returns integer as $$
declare n integer;
begin
  -- Our own price first, so the ratio's two sides are paired by one event.
  -- ON CONFLICT DO NOTHING, not DO UPDATE: the first write of the day wins and
  -- is then immutable. DO UPDATE would let a later crawl retroactively restate
  -- a historical point, which is the very bug this table exists to prevent.
  insert into precios_fs_diario (fecha, modelo, precio, precio_rebaja, en_rebaja)
  select p_fecha, m.modelo, m.precio, m.precio_rebaja, m.en_rebaja
  from models m
  on conflict (fecha, modelo) do nothing;

  delete from posicionamiento_historico where fecha = p_fecha;

  insert into posicionamiento_historico (
    fecha, modelo, competidor, competidor_slug,
    precio_fs, precio_comp, posicionamiento, es_mas_barato,
    skus_vistos, observed_at)
  select
    d.fecha, d.modelo, c.name, d.competitor_slug,
    p.precio_rebaja,
    d.precio_comp,
    case when p.precio_rebaja is not null and d.precio_comp > 0
         then round(p.precio_rebaja / d.precio_comp * 100, 2) end,
    d.precio_comp = min(d.precio_comp) over (partition by d.fecha, d.modelo),
    d.skus_vistos, d.observed_at
  from v_ofertas_emparejadas_diarias d
  join competitors c on c.slug = d.competitor_slug
  left join precios_fs_diario p on p.fecha = d.fecha and p.modelo = d.modelo
  where d.fecha = p_fecha and d.precio_comp > 0;

  get diagnostics n = row_count;
  return n;
end;
$$ language plpgsql
  set search_path = public;

-- Replays any range from the append-only competitor_offers. Day by day rather
-- than one big statement, so a replay never holds a long lock on the table the
-- page is reading.
create or replace function rebuild_posicionamiento_historico(
  p_desde date, p_hasta date
) returns integer as $$
declare d date; total integer := 0;
begin
  d := p_desde;
  while d <= p_hasta loop
    total := total + refresh_posicionamiento_historico(d);
    d := d + 1;
  end loop;
  return total;
end;
$$ language plpgsql
  set search_path = public;

revoke all on function refresh_posicionamiento_historico(date) from public, anon, authenticated;
revoke all on function rebuild_posicionamiento_historico(date, date) from public, anon, authenticated;
