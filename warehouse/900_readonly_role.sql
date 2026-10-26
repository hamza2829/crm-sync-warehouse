CREATE ROLE crm_reader NOLOGIN;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO crm_reader;
GRANT SELECT ON model_funnel, model_monthly_revenue, stg_deal_events TO crm_reader;
