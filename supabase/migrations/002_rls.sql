-- Public, read-only access for the landing page.
-- The dataset is reference data: anonymous visitors may read it, nobody may
-- write it through the API. Loading happens with the service_role key, which
-- bypasses RLS by design.

alter table brands enable row level security;
alter table models enable row level security;
alter table skus   enable row level security;

drop policy if exists "brands are publicly readable" on brands;
create policy "brands are publicly readable"
  on brands for select to anon, authenticated using (true);

drop policy if exists "models are publicly readable" on models;
create policy "models are publicly readable"
  on models for select to anon, authenticated using (true);

drop policy if exists "skus are publicly readable" on skus;
create policy "skus are publicly readable"
  on skus for select to anon, authenticated using (true);

-- No insert/update/delete policies exist, so with RLS enabled every anonymous
-- write is rejected. Verified explicitly in scripts/verify_api.sh.

grant usage on schema public to anon, authenticated;
grant select on brands, models, skus to anon, authenticated;
