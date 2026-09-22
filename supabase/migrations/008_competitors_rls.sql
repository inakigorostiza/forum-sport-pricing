-- Row level security for the competitor tables.
--
-- These are deliberately NOT public, unlike brands/models/skus.
--
-- The catalogue is product data a visitor could see on forumsport.com anyway.
-- Competitive price monitoring is different: it is Forum Sport's commercial
-- analysis of its rivals, and the aggregate (who we undercut, by how much, on
-- what stock position) is exactly what a competitor would want. Individual
-- prices are public on the rivals' own sites; this assembled view of them is not.
--
-- So: RLS on, and NO select policy for anon or authenticated. Only the
-- service_role key (which bypasses RLS) can read or write these tables, which
-- is what the scraper and any server-side consumer use.
--
-- When the landing page needs a comparison UI, expose a narrow aggregated view
-- rather than opening these tables.

alter table competitors         enable row level security;
alter table competitor_products enable row level security;
alter table competitor_offers   enable row level security;
alter table crawl_log           enable row level security;

-- Defence in depth, as in 004: Supabase grants ALL on new public objects to
-- anon/authenticated by default. Strip every privilege, not just writes.
revoke all on competitors, competitor_products, competitor_offers, crawl_log
  from anon, authenticated;
