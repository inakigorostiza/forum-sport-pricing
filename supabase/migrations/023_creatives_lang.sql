-- Creative Studio: the language of a creative's copy (English by default).
alter table creatives add column if not exists lang text not null default 'en' check (lang in ('en','es'));

create or replace view creatives_public
with (security_invoker = false) as
  select c.id, c.modelo, m.brand_code as marca, m.nombre_modelo, c.kind, c.channel,
         c.format, c.aspect, c.goal, c.price_now, c.price_rec, c.image_url,
         c.video_url, c.cost_credits, c.created_at, c.lang
  from creatives c
  join models m on m.modelo = c.modelo
  where c.status = 'done';

grant select on creatives_public to anon, authenticated;
