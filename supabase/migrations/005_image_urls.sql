-- Product imagery.
--
-- Pattern reverse-engineered from a real asset URL and verified against the
-- live CDN:
--   /images/{slug}-lateral-exterior-{modelo}-{size}-f
--
-- Findings that shape this:
--   · the {slug} is decorative — a junk slug returns the byte-identical image,
--     so resolution depends only on {modelo}. We still build a readable slug.
--   · 'lateral-exterior' (the shot) IS required; without it the CDN answers
--     200 with a zero-byte body.
--   · only 200x200, 500x500 and 1000x1000 exist. Any other size also answers
--     200 with 0 bytes — so a bad size fails silently, not loudly.
--   · sampled 26 models spanning the 12 largest brands: 26/26 had an image.
--
-- Immutability: translate/lower/regexp_replace are all immutable, so this is
-- valid in a generated column. unaccent() is NOT (it depends on a dictionary)
-- and is deliberately avoided.

alter table models
  add column if not exists img_slug text generated always as (
    trim(both '-' from regexp_replace(
      lower(translate(brand_code || ' ' || tipo_producto || ' ' || nombre_modelo,
        'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ',
        'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')),
      '[^a-z0-9]+', '-', 'g'))
  ) stored;

alter table models
  add column if not exists img_thumb text generated always as (
    'https://www.forumsport.com/images/' ||
    trim(both '-' from regexp_replace(
      lower(translate(brand_code || ' ' || tipo_producto || ' ' || nombre_modelo,
        'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ',
        'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')),
      '[^a-z0-9]+', '-', 'g')) ||
    '-lateral-exterior-' || modelo::text || '-200x200-f'
  ) stored;

alter table models
  add column if not exists img_full text generated always as (
    'https://www.forumsport.com/images/' ||
    trim(both '-' from regexp_replace(
      lower(translate(brand_code || ' ' || tipo_producto || ' ' || nombre_modelo,
        'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ',
        'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')),
      '[^a-z0-9]+', '-', 'g')) ||
    '-lateral-exterior-' || modelo::text || '-1000x1000-f'
  ) stored;

comment on column models.img_thumb is '200x200 product shot. Only 200/500/1000 exist; other sizes return an empty 200.';
comment on column models.img_full  is '1000x1000 product shot.';
