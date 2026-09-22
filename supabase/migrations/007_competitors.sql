-- Competitor price monitoring.
--
-- The whole design turns on one fact established by testing, not assumption:
-- 24.108 of our 24.109 EANs are globally resolvable GS1 codes, so the EAN is a
-- near-perfect join key between our catalogue and a competitor's product page.
--
-- The trap: 50,7 % of our EANs are stored as 12-digit UPCs and the rest as
-- 13-digit EANs. Competitors publish schema.org `gtin13`. A raw ean = gtin13
-- join would therefore silently drop half the catalogue. Both sides are
-- normalised to 13 digits, ours by a generated column so it can never drift.

alter table skus
  add column if not exists gtin13 text
  generated always as (lpad(ean::text, 13, '0')) stored;

comment on column skus.gtin13 is
  'EAN normalised to GTIN-13 (12-digit UPCs left-padded). Join key to competitor_offers.';

create index if not exists idx_skus_gtin13 on skus (gtin13);

create table if not exists competitors (
  slug           text primary key,            -- 'atmosfera-sport'
  name           text not null,               -- 'Atmósfera Sport'
  classification text not null,               -- from the source list, in Spanish
  base_url       text not null,
  records_ref    integer,                     -- "Record Count" from the source list
  strategy       text not null
    check (strategy in ('sitemap_jsonld', 'headless')),
  crawl_delay_s  numeric(4,1) not null default 2.0 check (crawl_delay_s >= 0.5),
  robots_status  text,                        -- 'allowed' | 'blocked_403' | 'unknown'
  sitemap_url    text,
  enabled        boolean not null default false,
  notes          text
);

comment on table competitors is
  'Crawl policy per competitor. enabled defaults to false: a site is crawled only after its policy has been checked deliberately.';
comment on column competitors.crawl_delay_s is
  'Minimum seconds between requests to this host. Honours robots.txt Crawl-delay where published.';

-- One discovered product page (a single colourway) and the crawl frontier.
create table if not exists competitor_products (
  id              bigint generated always as identity primary key,
  competitor_slug text not null references competitors(slug) on delete cascade,
  url             text not null,
  ext_id          text,                       -- productGroupID / sku on their side
  title           text,
  brand_raw       text,
  mpn             text,
  is_relevant     boolean not null default false,  -- has matched our catalogue
  first_seen      timestamptz not null default now(),
  last_seen       timestamptz not null default now(),
  last_error      text,
  unique (competitor_slug, url)
);

comment on column competitor_products.is_relevant is
  'Set once a variant matched our catalogue. The daily refresh crawls only these.';

-- Price observations. APPEND-ONLY: this is a time series, never updated in
-- place, so any repricing decision can be traced back to the observation and
-- the raw payload behind it.
create table if not exists competitor_offers (
  id              bigint generated always as identity primary key,
  competitor_slug text not null references competitors(slug) on delete cascade,
  product_id      bigint not null references competitor_products(id) on delete cascade,
  observed_at     timestamptz not null default now(),
  gtin13          text,                       -- normalised by the scraper
  mpn             text,
  size_raw        text,
  price           numeric(10,2) not null check (price >= 0),
  list_price      numeric(10,2) check (list_price >= 0),
  currency        char(3) not null default 'EUR',
  availability    text,                       -- InStock / OutOfStock / PreOrder
  promo_text      text,
  shipping_cost   numeric(10,2),
  url             text,
  raw             jsonb,                      -- extracted node, kept for audit
  constraint list_price_gte_price check (list_price is null or list_price >= price)
);

comment on table competitor_offers is
  'Append-only price history. Current price is a view (v_precio_actual_competencia), not a column.';

create index if not exists idx_offers_gtin13     on competitor_offers (gtin13, observed_at desc);
create index if not exists idx_offers_competitor on competitor_offers (competitor_slug, observed_at desc);
create index if not exists idx_offers_product    on competitor_offers (product_id);

-- Every fetch, so the crawl is auditable and politeness is provable.
create table if not exists crawl_log (
  id              bigint generated always as identity primary key,
  competitor_slug text not null references competitors(slug) on delete cascade,
  phase           text not null check (phase in ('discover', 'refresh')),
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  pages_fetched   integer not null default 0,
  offers_found    integer not null default 0,
  offers_matched  integer not null default 0,
  errors          integer not null default 0,
  min_gap_s       numeric(6,2),               -- smallest observed inter-request gap
  notes           text
);

comment on column crawl_log.min_gap_s is
  'Smallest gap actually observed between requests. Must never fall below the configured crawl_delay_s.';
