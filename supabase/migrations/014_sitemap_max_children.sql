-- How many child sitemaps to walk for this shop.
--
-- The default of 12 is a safety cap for shops whose sitemap index fans out into
-- hundreds of children. The Emotion family paginates its product sitemaps
-- (31 children of 1.000 URLs at Fútbol Emotion), so the cap silently truncated
-- discovery to a third of the catalogue. NULL keeps the code default.
alter table competitors
  add column if not exists sitemap_max_children smallint
    check (sitemap_max_children is null or sitemap_max_children between 1 and 200);

comment on column competitors.sitemap_max_children is
  'Child-sitemap fan-out limit for discovery. NULL = the crawler default (12).';
