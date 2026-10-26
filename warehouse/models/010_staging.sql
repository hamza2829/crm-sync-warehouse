CREATE OR REPLACE VIEW stg_deals AS
SELECT id, name, company_id, contact_id, stage, amount, currency,
       created_at, updated_at, close_date,
       SUBSTR(CAST(close_date AS TEXT), 1, 7) AS close_month
FROM raw_deals;
CREATE OR REPLACE VIEW stg_companies AS
SELECT id, name, industry, updated_at FROM raw_companies;
CREATE OR REPLACE VIEW stg_contacts AS
SELECT id, company_id, email, updated_at FROM raw_contacts;
CREATE OR REPLACE VIEW stg_deal_events AS
SELECT event_id, event_time, deal_id, old_stage, new_stage FROM deal_events;
