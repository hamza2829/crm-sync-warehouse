"""These tests deliberately refuse to run outside GitHub Actions."""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from pipeline.storage import SQL_ROOT, Database
from pipeline.sync import extract, sync
from pipeline.webhook import create_app
from quality.checks import QualityError, run_checks

pytestmark = pytest.mark.integration


@pytest.fixture
def pg():
    if os.getenv("GITHUB_ACTIONS") != "true" or not os.getenv("DATABASE_URL"):
        pytest.skip("TimescaleDB integration tests run only in GitHub Actions")
    db = Database()
    assert db.postgres
    db.initialize()
    db.run_models()
    with db.connect() as connection:
        connection.execute("""TRUNCATE raw_deals, raw_companies, raw_contacts, quarantine,
                            sync_state, sync_runs, deal_events, quality_results""")
    yield db


def test_full_sync_twice_identical_raw_tables(pg, crm):
    sync(pg, crm)
    tables = ("raw_deals", "raw_companies", "raw_contacts", "sync_state", "deal_events")
    before = {table: pg.rows(f"SELECT * FROM {table} ORDER BY 1") for table in tables}
    sync(pg, crm)
    assert {table: pg.rows(f"SELECT * FROM {table} ORDER BY 1") for table in tables} == before
    assert len(before["raw_deals"]) == 500


def test_drift_is_jsonb_and_quarantined(pg, crm, tmp_path):
    run_id = sync(pg, crm, drift=True)
    rows = pg.rows("SELECT * FROM quarantine")
    assert len(rows) == 500 and isinstance(rows[0]["raw"], dict)
    assert "amount" in rows[0]["reason"]
    with pytest.raises(QualityError):
        run_checks(pg, run_id, report_path=tmp_path / "drift.md")


def test_webhook_end_to_end_and_timescale_hypertable(pg, api, monkeypatch):
    monkeypatch.setenv("CRM_WEBHOOK_URL", "/webhooks/deals")
    with TestClient(create_app(pg)) as receiver:
        api.app.state.webhook_client = receiver
        old = api.app.state.data["deals"][0]["stage"]
        result = api.patch("/deals/1/stage", json={"stage": "won" if old != "won" else "lost"})
        result.raise_for_status()
        payload = result.json()["event"]
        receiver.post(
            "/webhooks/deals", json=payload, headers={"X-Webhook-Secret": "demo-secret"}
        ).raise_for_status()
    assert len(pg.rows("SELECT * FROM deal_events")) == 1
    assert pg.rows(
        "SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name='deal_events'"
    )


def test_incremental_update_and_models(pg, crm, api, tmp_path):
    sync(pg, crm)
    old = api.app.state.data["deals"][0]["stage"]
    api.patch("/deals/1/stage", json={"stage": "won" if old != "won" else "lost"})
    assert len(extract(pg, crm)["records"]["deals"]) == 1
    run_id = sync(pg, crm)
    pg.run_models()
    assert len(pg.rows("SELECT * FROM model_monthly_revenue")) == 12
    assert all(row["passed"] for row in run_checks(pg, run_id, report_path=tmp_path / "ok.md"))


def test_postgres_readonly_transaction(pg):
    with (
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
        pg.connect(readonly=True) as connection,
    ):
        connection.execute("INSERT INTO sync_state VALUES ('blocked', 'blocked', NOW())")


def test_reader_role_has_only_fixed_view_access(pg):
    # A fresh service container has no pre-existing application role.
    pg.apply_sql(SQL_ROOT / "900_readonly_role.sql")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), pg.connect() as connection:
        connection.execute("SET ROLE crm_reader")
        assert connection.execute("SELECT * FROM model_funnel").fetchall() == []
        connection.execute("INSERT INTO sync_state VALUES ('blocked', 'blocked', NOW())")
