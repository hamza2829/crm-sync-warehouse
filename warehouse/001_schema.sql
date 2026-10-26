CREATE TABLE IF NOT EXISTS raw_companies (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, industry TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL, raw JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_contacts (
    id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, email TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL, raw JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_deals (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, company_id INTEGER NOT NULL,
    contact_id INTEGER NOT NULL, stage TEXT NOT NULL, amount NUMERIC,
    currency TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL, close_date DATE NOT NULL, raw JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
    resource TEXT PRIMARY KEY, cursor TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id TEXT PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL,
    rows_seen INTEGER NOT NULL, rows_loaded INTEGER NOT NULL,
    quarantined INTEGER NOT NULL, row_count INTEGER NOT NULL, drift JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS quarantine (
    run_id TEXT NOT NULL, resource TEXT NOT NULL, record_id TEXT NOT NULL,
    reason TEXT NOT NULL, raw JSONB NOT NULL, quarantined_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, resource, record_id)
);
CREATE TABLE IF NOT EXISTS deal_events (
    event_id TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL, deal_id INTEGER NOT NULL,
    old_stage TEXT NOT NULL, new_stage TEXT NOT NULL, received_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (event_time, event_id)
);
CREATE TABLE IF NOT EXISTS quality_results (
    run_id TEXT NOT NULL, check_name TEXT NOT NULL, passed BOOLEAN NOT NULL,
    observed JSONB NOT NULL, expectation TEXT NOT NULL, checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);
