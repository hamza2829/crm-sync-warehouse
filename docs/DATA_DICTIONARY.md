# Data dictionary

All records are synthetic. Source paths refer to the mock API, never to a real CRM.
All amounts are USD. Source timestamps are timezone-aware UTC; PostgreSQL stores
TIMESTAMPTZ and SQLite stores ISO 8601 text. PostgreSQL raw payloads are JSONB;
SQLite stores equivalent JSON text. Ids are synthetic positive integers.

| Table | Columns | Meaning and source |
| --- | --- | --- |
| raw_companies | id, name, industry, updated_at | Direct fields from GET /companies. id is the primary key; updated_at is the source update time. |
| raw_companies | raw | Untouched company JSON, including unknown fields. |
| raw_contacts | id, company_id, email, updated_at | Direct fields from GET /contacts. id is the primary key; company_id points to a company. Emails use example.invalid. |
| raw_contacts | raw | Untouched contact JSON, including unknown fields. |
| raw_deals | id, name | Direct mock GET /deals fields: primary key and display name. |
| raw_deals | company_id, contact_id | Source company and contact references. These are logical relationships, without enforced foreign keys so ingestion order stays independent. |
| raw_deals | stage | Source current state: lead, qualified, proposal, won or lost. |
| raw_deals | amount, currency | Source nominal amount and USD currency. amount may be NULL; quality rejects NULL amounts on won deals. Negative or non-finite amounts are quarantined. |
| raw_deals | created_at, updated_at | Source creation and last modification times. updated_at plus id orders incremental pagination. |
| raw_deals | close_date | Source expected close date for open deals; recorded close date for terminal deals. Seeded open deals have overdue dates to demonstrate risk. |
| raw_deals | raw | Complete original JSON. Unknown fields stay here, without changing typed columns. |
| sync_state | resource | Primary key. Only deals currently has an incremental checkpoint. |
| sync_state | cursor | Base64 JSON of the last source updated_at and id, including quarantined deals. |
| sync_state | updated_at | Warehouse time when that checkpoint was committed. |
| sync_runs | run_id, started_at | Pipeline-generated UUID and extraction start time. One row per committed load, including no-op loads. |
| sync_runs | rows_seen, rows_loaded, quarantined | Counts across all three resources for this batch. rows_loaded counts validated records upserted, not only newly inserted ids. |
| sync_runs | row_count | Total warehouse deal count after the load, used as the next quality baseline. |
| sync_runs | drift | JSON per resource: unknown_fields, rejected count, seen count. Also written to the run log and report. |
| quarantine | run_id, resource, record_id | Composite key tying a rejected source record to its load and resource. Source id is text to retain malformed identifiers; a missing id uses a batch row index prefixed with missing-. |
| quarantine | reason, raw | Validation errors and untouched rejected source JSON. Renames are not guessed. |
| quarantine | quarantined_at | Warehouse time when rejection was recorded. |
| deal_events | event_id, event_time | Producer UUID and source stage-change time. Composite primary key also provides replay deduplication; event_time is the Timescale partition key. |
| deal_events | deal_id, old_stage, new_stage | Source changed deal id and previous/new states from the mock stage mutation webhook. |
| deal_events | received_at | Warehouse receiver time, separate from event_time. |
| quality_results | run_id, check_name | Composite key. Check names: unique_ids, won_amounts, row_count, freshness, quarantine_rate. |
| quality_results | passed | Boolean decision. Failure raises an error after all results and the report are saved. |
| quality_results | observed, expectation | JSON metric and human-readable threshold used for that decision. |
| quality_results | checked_at | Warehouse check execution time. |

Staging views remove raw payloads and retain the identically named, typed columns
documented above: stg_deals, stg_companies, stg_contacts. stg_deals adds close_month
as YYYY-MM from close_date. stg_deal_events exposes event_id, event_time, deal_id,
old_stage and new_stage, without receiver metadata.

| Model | Column | Derivation |
| --- | --- | --- |
| model_funnel | stage, stage_order | Five fixed labels and display order. lost is a separate terminal outcome. |
| model_funnel | current_deals | Count currently in that stage. |
| model_funnel | reached_deals | Snapshot proxy: all deals reached lead; qualified includes qualified/proposal/won; proposal includes proposal/won; won and lost count their current members. Earlier progression is assumed, not measured. |
| model_funnel | conversion_rate | reached_deals divided by the preceding funnel step. Lead is 1; lost is lost/all; a zero denominator gives NULL. These are snapshot ratios, not historical cohort conversion. |
| model_monthly_revenue | month, currency | close_month and USD from stg_deals; one row per observed month/currency. |
| model_monthly_revenue | deal_count | All deals with that close month. |
| model_monthly_revenue | pipeline_amount, open_deals | Sum of nonterminal amounts (NULL treated as 0) and their count. This is the current snapshot, not past pipeline snapshots. |
| model_monthly_revenue | won_revenue, won_deals | Sum of won amounts and their count by source close month. No accounting recognition or invoice integration is implied. |

Only events generated after stage changes are retained. Seeded deals have no
fabricated historical events. The forecast fills missing calendar months with
zero revenue, excludes the current incomplete month, and labels its next three
calendar months relative to the report date.
