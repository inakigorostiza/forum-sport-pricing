-- Defense in depth.
--
-- Supabase's default privileges grant ALL (INSERT/UPDATE/DELETE/TRUNCATE) on
-- every new object in `public` to anon and authenticated. RLS then blocks the
-- writes at row level, which is why an anonymous DELETE affects 0 rows and
-- PostgREST answers 204 rather than an error.
--
-- For a read-only public dataset that is one layer too few: anyone who later
-- disables RLS on a table makes it world-writable. Strip the write privileges
-- so the grant layer and the RLS layer both have to fail before data can be
-- modified.

revoke all on all tables in schema public from anon, authenticated;

grant select on all tables in schema public to anon, authenticated;

-- Apply the same rule to objects created later by migrations.
alter default privileges in schema public
  revoke insert, update, delete, truncate on tables from anon, authenticated;

alter default privileges for role postgres in schema public
  revoke insert, update, delete, truncate on tables from anon, authenticated;
