-- The API role's privileges in one schema (PLAN.md Q7, Q65, Q70, Q76).
-- Applied in one transaction by `python -m codeask.admin grants ROLE`, as the owner over the
-- direct URL; re-run after any schema change. Idempotent: revoke from the role, then grant.
-- Revokes from the role only, never from PUBLIC. The braced names are filled in as quoted
-- identifiers. Content tables: read only. usage_settings: read and update (pause, budget,
-- blocked_until; accepted in Q7). usage_hourly, usage_daily: read, insert, update.
-- No DELETE or TRUNCATE anywhere.
REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {role};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {role};
REVOKE ALL ON SCHEMA {schema} FROM {role};
GRANT USAGE ON SCHEMA {schema} TO {role};
GRANT SELECT ON {schema}.repos, {schema}.chunks, {schema}.embeddings TO {role};
GRANT SELECT, UPDATE ON {schema}.usage_settings TO {role};
GRANT SELECT, INSERT, UPDATE ON {schema}.usage_hourly, {schema}.usage_daily TO {role};
