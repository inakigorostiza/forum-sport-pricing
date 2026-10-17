-- Creative Studio: creatives generated from a model's recommended price.
--
-- Writes only through the `creative-studio` Edge Function (service role,
-- behind the operator token): generating spends real money on Higgsfield,
-- so nothing here is writable by `anon`. The public reads finished creatives
-- through `creatives_public`, which leaves out the prompt, the provider's
-- request ids and the error text.

create table if not exists creatives (
  id             uuid primary key default gen_random_uuid(),
  modelo         bigint not null references models(modelo),
  kind           text not null check (kind in ('image','video')),
  channel        text not null,
  format         text not null,
  aspect         text not null,
  goal           text not null,
  prompt         text,
  price_now      numeric(10,2) not null,
  price_rec      numeric(10,2) not null,
  status         text not null default 'queued'
                 check (status in ('queued','still','motion','done','failed')),
  hf_image_req   text,
  hf_video_req   text,
  image_url      text,          -- branded still, logo composited
  video_url      text,          -- video only
  cost_credits   numeric(10,2),
  error          text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists creatives_created_idx on creatives (created_at desc);
create index if not exists creatives_modelo_idx  on creatives (modelo);

alter table creatives enable row level security;
-- No policies: only the service role reads or writes the table itself.

create or replace view creatives_public
with (security_invoker = false) as
  select c.id, c.modelo, m.brand_code as marca, m.nombre_modelo, c.kind, c.channel,
         c.format, c.aspect, c.goal, c.price_now, c.price_rec, c.image_url,
         c.video_url, c.cost_credits, c.created_at
  from creatives c
  join models m on m.modelo = c.modelo
  where c.status = 'done';

grant select on creatives_public to anon, authenticated;

-- Public bucket for the finished media. Reads are public by bucket setting;
-- uploads go through the service role only.
insert into storage.buckets (id, name, public)
values ('creatives', 'creatives', true)
on conflict (id) do update set public = true;

-- The table itself is service-role only; the public reads creatives_public.
revoke all on creatives from anon, authenticated;
