-- Which User-Agent to identify as for this shop.
--
-- The crawler declares itself honestly by default. A few shops answer 403 to
-- any non-browser UA: The North Face returned 68 errors in 76 fetches under the
-- honest UA and serves the same page normally to a browser UA. Making this an
-- explicit, per-shop, opt-in column keeps that decision visible and auditable
-- rather than hiding a blanket UA change in the fetcher.
alter table competitors
  add column if not exists user_agent text not null default 'honest'
    check (user_agent in ('honest', 'browser'));

comment on column competitors.user_agent is
  'honest = identify as the Forum Sport crawler (default); browser = send a browser UA, for shops that 403 every other client.';
