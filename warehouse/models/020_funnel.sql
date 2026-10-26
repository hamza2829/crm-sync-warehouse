CREATE OR REPLACE VIEW model_funnel AS
WITH stages AS (
    SELECT 'lead' AS stage, 1 AS stage_order
    UNION ALL SELECT 'qualified', 2
    UNION ALL SELECT 'proposal', 3
    UNION ALL SELECT 'won', 4
    UNION ALL SELECT 'lost', 5
), counts AS (
    SELECT s.stage, s.stage_order,
        SUM(CASE WHEN d.stage = s.stage THEN 1 ELSE 0 END) AS current_deals,
        SUM(CASE
            WHEN s.stage = 'lead' THEN 1
            WHEN s.stage = 'qualified' AND d.stage IN ('qualified','proposal','won') THEN 1
            WHEN s.stage = 'proposal' AND d.stage IN ('proposal','won') THEN 1
            WHEN s.stage = d.stage AND s.stage IN ('won','lost') THEN 1
            ELSE 0 END) AS reached_deals
    FROM stages s CROSS JOIN stg_deals d
    GROUP BY s.stage, s.stage_order
), denominators AS (
    SELECT *, CASE WHEN stage = 'lost' THEN (SELECT COUNT(*) FROM stg_deals)
                  ELSE LAG(reached_deals) OVER (ORDER BY stage_order) END AS previous_deals
    FROM counts
)
SELECT stage, stage_order, current_deals, reached_deals,
    CASE WHEN stage = 'lead' THEN 1.0
         ELSE 1.0 * reached_deals / NULLIF(previous_deals, 0) END AS conversion_rate
FROM denominators;
