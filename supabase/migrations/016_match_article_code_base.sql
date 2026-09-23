-- Match the article code on the full value OR on its base, not just verbatim.
--
-- The crawler accepted an offer when the part of the competitor's mpn before
-- the first "-" equalled our ref_prov, but this view required the two to be
-- equal outright. Offers were therefore stored and then silently dropped before
-- reaching the landing page: Basketball Emotion wrote 10 Nike offers
-- ("FN8454-800", "FQ7262-103") and produced zero comparison rows.
--
-- Neither rule alone is right, because the two sides carry colour differently:
--   NIKE    ref_prov CD4371      vs their FQ7262-103  -> base match needed
--   SAUCONY ref_prov S29101-01   vs their S29101-01   -> exact match needed
-- (49 of our 56 Saucony models carry the colour suffix; none of our 239 Nike
-- models do.) So accept either, and keep it a model-level match.

create or replace view v_ofertas_emparejadas with (security_invoker = on) as
-- 1. GTIN path: size-exact.
select
  o.id, o.competitor_slug, o.product_id, o.observed_at, o.gtin13, o.mpn,
  o.size_raw, o.price, o.list_price, o.currency, o.availability,
  o.promo_text, o.shipping_cost, o.url,
  s.modelo,
  'gtin13'::text as match_method
from competitor_offers o
join skus s on s.gtin13 = o.gtin13
where o.gtin13 is not null

union all

-- 2. Article-code path: model-level, for sellers that publish no GTIN.
select distinct on (o.id, m.modelo)
  o.id, o.competitor_slug, o.product_id, o.observed_at, o.gtin13, o.mpn,
  o.size_raw, o.price, o.list_price, o.currency, o.availability,
  o.promo_text, o.shipping_cost, o.url,
  m.modelo,
  'ref_prov'::text
from competitor_offers o
join models m
  on upper(m.ref_prov) = upper(o.mpn)
  or upper(m.ref_prov) = upper(split_part(o.mpn, '-', 1))
where o.gtin13 is null and o.mpn is not null;

comment on view v_ofertas_emparejadas is
  'Offers joined to our catalogue by GTIN-13 (size-exact) or article code (model-level, full value or the part before the first hyphen). match_method says which.';
