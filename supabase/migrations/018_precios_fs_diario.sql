-- A daily snapshot of OUR price, so the positioning ratio has a real numerator.
--
-- The problem this fixes: models.precio_rebaja is a single snapshot column with
-- no history, no updated_at and no trigger. Plotting "our price / their price"
-- over time against it would recompute every historical point from TODAY's
-- numerator, so repricing one model today would retroactively change what the
-- chart says about last month. A chart that rewrites its own past is worse than
-- no chart.
--
-- Written by the crawler, inside the same call that records competitor prices,
-- so the two sides of the ratio are always paired by the same event. A separate
-- cron would drift: a failed crawl would leave a day with our price and no
-- competitor price, which reads as "we lost all coverage" rather than the truth,
-- "we did not look".
--
-- Private on purpose. The chart never reads this table: the public history
-- carries a denormalised copy of just the one price it needs. The column list
-- is the security boundary, same reasoning as 010 — margen, neto and
-- cobertura_stock are deliberately absent.
create table if not exists precios_fs_diario (
  fecha         date          not null,
  modelo        bigint        not null references models(modelo) on delete cascade,
  precio        numeric(10,2) not null,     -- PVP
  precio_rebaja numeric(10,2) not null,     -- the number the ratio actually uses
  en_rebaja     boolean       not null,
  primary key (fecha, modelo)
);

comment on table precios_fs_diario is
  'Daily snapshot of our own price. First write of a day wins and is then immutable.';

alter table precios_fs_diario enable row level security;
-- No select policy: with RLS on and no policy, anon and authenticated read
-- nothing. Same posture as the competitor tables in 008.
revoke all on precios_fs_diario from anon, authenticated;
