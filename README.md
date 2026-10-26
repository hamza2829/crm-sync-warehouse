# crm-sync-warehouse

[![CI](https://github.com/hamza2829/crm-sync-warehouse/actions/workflows/ci.yml/badge.svg)](https://github.com/hamza2829/crm-sync-warehouse/actions/workflows/ci.yml)

A small, explainable pipeline from a synthetic mock CRM to a reporting warehouse.
It demonstrates incremental reads, retries, idempotent loads, drift quarantine,
stage history, SQL models, quality gates and a simple forecast.

**The CRM has a HubSpot-like API shape. It is not a HubSpot or Salesforce
integration. All data is synthetic.** There are 25 companies, 100 contacts and
500 deals across 12 complete months. All amounts are USD.

```text
Synthetic FastAPI CRM                 PATCH stage change
  GET companies / contacts / deals          |
                 |                   POST webhook + secret
       bounded retry client                 |
                 |                   FastAPI receiver
     extract -> validate                    |
                 |                   deal_events hypertable
          atomic load                       |
       /      |       \                     |
 raw tables  cursor  quarantine             |
       \       |       /                    |
        versioned SQL models <--------------+
                 |
        persisted quality gates
                 |
     linear forecast -> offline dashboard
                 \----> fixed read queries / text answer

Local: Python 3.11+ + SQLite, no Docker, no Airflow
CI: Python 3.11 / 3.13 tests + TimescaleDB PG16 + Airflow 3.1.8
```

## Run locally on Windows

Install Python 3.11 or newer with its Python launcher, then use PowerShell.
Calling the environment's executable directly avoids activation-policy changes.

```powershell
git clone https://github.com/hamza2829/crm-sync-warehouse.git
cd crm-sync-warehouse
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Default pytest selection excludes integration tests. No database service is needed.
Run the complete in-process demo with a SQLite file:

```powershell
.\.venv\Scripts\python.exe -m pipeline demo
Start-Process .\artifacts\dashboard.html
Get-Content .\docs\last_run_report.md
.\.venv\Scripts\python.exe -m pipeline answer
```

The dashboard bundles Plotly JavaScript and works offline. `demo` uses an
in-process mock API, without a background server. Each invocation reseeds source
timestamps. Use the long-lived API below to observe a no-change incremental run.

In one terminal, start the mock CRM:

```powershell
$env:WEBHOOK_SECRET = "local-demo-only"
$env:CRM_WEBHOOK_URL = "http://127.0.0.1:8001/webhooks/deals"
.\.venv\Scripts\python.exe -m uvicorn mock_crm.app:app --port 8000
```

In a second terminal, initialize SQLite and start the receiver:

```powershell
$env:WEBHOOK_SECRET = "local-demo-only"
.\.venv\Scripts\python.exe -m pipeline init
.\.venv\Scripts\python.exe -m uvicorn pipeline.webhook:app --port 8001
```

In a third terminal, sync twice and generate a stage event:

```powershell
.\.venv\Scripts\python.exe -m pipeline sync
.\.venv\Scripts\python.exe -m pipeline sync
Invoke-RestMethod http://127.0.0.1:8000/deals/1/stage -Method Patch `
  -ContentType "application/json" -Body '{"stage":"won"}'
.\.venv\Scripts\python.exe -m pipeline sync
```

The second sync fetches zero deals. Companies and contacts are small full
snapshots fetched every run. Changing to the same stage emits no event, so choose
another stage if deal 1 is already won. Swagger is at http://127.0.0.1:8000/docs.
Mock state is in memory and resets on restart. Keeping SQLite across a CRM restart
causes the refreshed source timestamps to be fetched again.

`DATABASE_URL` defaults to `sqlite:///demo.db`; `--database-url` overrides it.
`CRM_URL` defaults to `http://127.0.0.1:8000`; `--crm-url` overrides it.
`python -m pipeline init` creates tables and models without fetching data.

## What runs only in CI

GitHub Actions runs lint and unit tests on Ubuntu with Python 3.11 and 3.13.
The integration job uses `timescale/timescaledb:latest-pg16` to verify JSONB,
hypertables and permissions. Airflow 3.1.8 uses a separate Python 3.11 environment
with its official constraints file and its own SQLite metadata database.
`airflow db migrate` initializes metadata, then `airflow dags test crm_sync` runs:

```text
extract -> validate -> load -> run_models -> data_quality_checks -> forecast -> report
```

XComs carry paths or run ids. Intermediate JSON files live by run id on the
runner's disk. The report task runs after quality failure, saves diagnostics and
fails again so an all_done leaf cannot hide bad quality. A missing forecast
artifact also fails the final task.

Download **crm-dashboard-and-run-report** from the
[Actions run](https://github.com/hamza2829/crm-sync-warehouse/actions) for the HTML,
Markdown, batches, forecast JSON and installed dependencies. The committed
[last run report](docs/last_run_report.md) is a local sample; CI artifacts contain
the report from that CI execution.

Airflow and TimescaleDB are only verified in GitHub Actions. Neither runs on the
local PC. The local commands require no Docker.

## Failure modes and sync semantics

| Problem | Trigger | Handling |
| --- | --- | --- |
| Rate limit | CRM_RATE_LIMIT=N before server start, or GET /deals?rate_limit=1. Zero disables it. | HTTP 429 has Retry-After. Client respects seconds or an HTTP date, otherwise exponential backoff. Four total attempts, with 1/2/4 second fallback waits. Also retries transport failures and 500/502/503/504. Exhaustion fails extraction without advancing the cursor. Other 4xx fail immediately. |
| Schema drift | CRM_SCHEMA_DRIFT=1, GET /deals?drift=true, or pipeline sync --drift on uncheckpointed records. | Mock renames amount to value, drops currency and adds campaign_code. Required-field errors quarantine the record with raw JSON and a reason. Unknown fields stay in raw JSONB. Drift counts and unknown field names are logged in sync_runs, the run log and report. Validation continues; excessive quarantine deliberately fails quality. |
| Webhook delivery | Set CRM_WEBHOOK_URL; PATCH /deals/{id}/stage. Unset URL disables delivery. An unavailable receiver simulates failure. | Receiver validates a shared secret and payload, then records the event. Identical event_time/event_id replays deduplicate. Failed synchronous delivery returns 502 without changing the mock stage. There is no durable outbox. |

Deals use `(updated_at, id)` ordering to avoid skipping equal timestamps at page
boundaries. A separate response-envelope checkpoint preserves progress even if
required fields disappear from individual records. The source must update
updated_at on every mutation; late arrivals
behind the cursor are outside this demo's guarantee. `ON CONFLICT (id) DO UPDATE`
keeps one row per source id. Data, quarantine, run log and cursor commit in one
transaction. A writer lock and checkpoint comparison reject stale batches.
Repeated syncs preserve raw tables while adding audit runs.

Quarantined records advance the cursor to avoid poison-record loops. After fixing
drift, explicitly replay from the beginning to recover them. For local SQLite,
clear only the deals checkpoint, retaining quarantine history:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('demo.db'); c.execute('DELETE FROM sync_state WHERE resource=?', ('deals',)); c.commit(); c.close()"
.\.venv\Scripts\python.exe -m pipeline sync
```

No renaming is guessed silently. Use
`python -m pipeline demo --drift --database-url sqlite:///drift-demo.db` for an
isolated failure demo. It intentionally exits nonzero and still saves a report
and dashboard.

## Models and quality

[DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) explains every stored and modeled column.
`warehouse/001_schema.sql` defines tables, `002_timescale.sql` creates the event
hypertable, and numbered files in `warehouse/models/` define staging and models.
PostgreSQL uses JSONB and TIMESTAMPTZ. SQLite uses JSON and timestamp text for
equivalent logic; this does not verify TimescaleDB behavior.

The funnel is a **snapshot proxy**: won deals are assumed to have passed through
qualified and proposal. Lost deals count in lead and lost, since their earlier
stage is unknown. Lost/all is a separate outcome rate. These are not historical
cohort conversions. New stage events are retained separately. Monthly pipeline
is current open amount by expected close month, not archived historical snapshots.
Won revenue uses the mock close date, not accounting recognition.

Each run stores these checks in quality_results and docs/last_run_report.md:

| Check | Default pass condition |
| --- | --- |
| unique_ids | Zero duplicate ids across all raw tables. Primary keys also enforce this. |
| won_amounts | Zero NULL amounts on won deals. |
| row_count | Positive total deals, within 20% of the previous committed run. First run requires a positive count. |
| freshness | Newest deal updated_at within 48 hours, with six minutes of future clock skew allowed. |
| quarantine_rate | Each resource's rejected/seen rate strictly below 5%; an empty batch has rate 0. |

All decisions are persisted before QualityError is raised. Failed or incomplete
quality withholds the forecast. Freshness checks the newest update, not every row.
Counts alone cannot prove first-load completeness.

## Forecast, dashboard and an answer

The forecast is ordinary least-squares linear trend on up to 12 complete months
of won revenue. It is easier to explain than ARIMA for a short synthetic series.
Missing calendar months mean zero, and the current incomplete month is excluded.
It predicts the next three calendar months relative to the report date, bridging
the excluded current month. Fewer than three training months use a constant mean.
Predictions and lower bands are clipped to zero. The +/-2 residual RMSE band is
illustrative, not a calibrated confidence interval. There is no seasonality,
causal model or claimed accuracy.

The dashboard makes metrics visible. An answer selects the relevant numbers and
explains their assumptions and risk. `answer_pipeline_question()` answers the
single supported question, "what is expected to close next month and what is the
risk", with the forecast, scheduled open pipeline, overdue count and USD amounts.
It withholds the answer when the latest run has failed or incomplete quality.

```python
from pipeline.forecast import answer_pipeline_question
from pipeline.storage import Database

print(answer_pipeline_question(Database("sqlite:///demo.db")))
```

Seeded open deals have overdue dates deliberately. A historical forecast with
no next-month scheduled pipeline is explicitly flagged as risk.

## Agent-ready access and permissions

Three fixed Python methods expose no SQL input or mutation:

```python
from pipeline.queries import ReadQueries

queries = ReadQueries("sqlite:///demo.db")
queries.funnel()
queries.monthly_revenue("2026-01", "2026-10")
queries.deal_history(1, limit=100)
```

Months must be valid YYYY-MM values, ordered and within ten calendar years.
Deal ids are positive integers and limits are 1..1000. Values are bound parameters.
The interface exposes no contact emails or raw payloads. SQLite uses mode=ro and
query_only. PostgreSQL uses read-only transactions. Integration tests verify
read-only transactions and restricted role permissions.

`warehouse/900_readonly_role.sql` is a one-time admin script creating the NOLOGIN
crm_reader role with only schema USAGE and SELECT on model_funnel,
model_monthly_revenue and stg_deal_events. Grant it to a dedicated login and use
that login's DSN. Agents should not receive writer credentials. The script
revokes PUBLIC schema access; review it before applying to a shared database.
It is tested in the disposable CI database. These Python methods are not a
sandbox for arbitrary Python code; database privileges provide the stronger boundary.

## Tests and project map

Unit tests cover cursor ties, retries, incremental changes, repeat loads, rollback,
quarantine, quality boundaries, query permissions, calendar forecasts and offline
reports. Integration tests are marked integration and refuse to run outside
GitHub Actions. They verify full sync twice, drift, webhooks, the hypertable,
incremental updates, models, quality and permissions against the real service.
There are 88 unit tests and six integration tests.

```text
mock_crm/     seed, pagination and stage mutation
pipeline/     client, validation, persistence, sync, receiver and reporting
warehouse/    versioned tables, Timescale setup, views and restricted role
quality/      metrics, decisions and quality reports
dags/         Airflow 3 crm_sync DAG
tests/        unit and CI-only integration tests
docs/         dictionary and generated sample report
```

The three project PRs cover [CRM and ingestion](https://github.com/hamza2829/crm-sync-warehouse/pull/1),
[warehouse and quality](https://github.com/hamza2829/crm-sync-warehouse/pull/2),
and [orchestration, forecast, dashboard and CI](https://github.com/hamza2829/crm-sync-warehouse/pull/3).

## Limits

Synthetic data, mock CRM, no real HubSpot or Salesforce connection, not production.
Airflow and TimescaleDB are only verified in GitHub Actions. The forecast is simple
and uncalibrated. There are no delete tombstones, persistent CRM server state,
durable webhook outbox, OAuth, webhook signatures, secrets management, retention
policy or distributed worker storage. The fallback secret demo-secret is only
for a local demo; use matching WEBHOOK_SECRET values in both processes.
Identical event replays deduplicate, but an ambiguous delivery followed by a
new event id can duplicate a logical transition. The DAG assumes a shared runner
disk and one active run. latest-pg16 floats as requested. Numbered SQL files are
repeatable setup, not a general schema migration framework.

References: [Airflow SDK](https://airflow.apache.org/docs/task-sdk/stable/),
[Airflow installation](https://airflow.apache.org/docs/apache-airflow/3.1.8/installation/installing-from-pypi.html),
[Timescale hypertables](https://docs.timescale.com/api/latest/hypertable/create_hypertable/).
