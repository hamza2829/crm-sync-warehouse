CREATE OR REPLACE VIEW model_monthly_revenue AS
SELECT close_month AS month, currency,
       COUNT(*) AS deal_count,
       SUM(CASE WHEN stage NOT IN ('won','lost') THEN COALESCE(amount,0) ELSE 0 END)
           AS pipeline_amount,
       SUM(CASE WHEN stage = 'won' THEN COALESCE(amount,0) ELSE 0 END) AS won_revenue,
       SUM(CASE WHEN stage = 'won' THEN 1 ELSE 0 END) AS won_deals,
       SUM(CASE WHEN stage NOT IN ('won','lost') THEN 1 ELSE 0 END) AS open_deals
FROM stg_deals GROUP BY close_month, currency;
