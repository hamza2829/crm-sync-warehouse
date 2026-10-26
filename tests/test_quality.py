from datetime import UTC, datetime, timedelta

import pytest

from pipeline.sync import sync
from quality.checks import QualityError, collect_metrics, evaluate, run_checks


def healthy():
    return {
        "duplicate_ids": 0,
        "won_null_amounts": 0,
        "row_count": 500,
        "previous_count": 500,
        "age_hours": 1,
        "quarantine_rate": 0,
    }


def test_all_quality_checks_pass():
    assert all(row["passed"] for row in evaluate(healthy()))


@pytest.mark.parametrize(
    "metric,value,check",
    [
        ("duplicate_ids", 1, "unique_ids"),
        ("won_null_amounts", 1, "won_amounts"),
        ("row_count", 300, "row_count"),
        ("row_count", 700, "row_count"),
        ("row_count", 0, "row_count"),
        ("age_hours", 49, "freshness"),
        ("age_hours", None, "freshness"),
        ("age_hours", -2, "freshness"),
        ("quarantine_rate", 0.05, "quarantine_rate"),
    ],
)
def test_quality_failure_boundaries(metric, value, check):
    metrics = {**healthy(), metric: value}
    results = {row["check_name"]: row for row in evaluate(metrics)}
    assert not results[check]["passed"]


def test_first_run_uses_positive_count_baseline():
    assert all(row["passed"] for row in evaluate({**healthy(), "previous_count": None}))


def test_quality_results_and_report_are_written(db, crm, tmp_path):
    run_id = sync(db, crm)
    report = tmp_path / "last_run_report.md"
    run_checks(db, run_id, report_path=report)
    assert len(db.rows("SELECT * FROM quality_results")) == 5
    assert "PASS" in report.read_text()
    assert collect_metrics(db, run_id, datetime.now(UTC) + timedelta(hours=60))["age_hours"] > 48


def test_failed_quality_is_persisted_before_raising(db, crm, tmp_path):
    run_id = sync(db, crm, drift=True)
    report = tmp_path / "failure.md"
    with pytest.raises(QualityError, match="quarantine_rate"):
        run_checks(db, run_id, report_path=report)
    assert len(db.rows("SELECT * FROM quality_results")) == 5
    assert "FAIL" in report.read_text()


def test_won_null_and_previous_count_metrics(db, crm, tmp_path):
    sync(db, crm)
    run_id = sync(db, crm)
    with db.connect() as connection:
        connection.execute("UPDATE raw_deals SET amount=NULL WHERE stage='won'")
    metrics = collect_metrics(db, run_id)
    assert metrics["previous_count"] == 500
    assert metrics["won_null_amounts"] > 0
    with pytest.raises(QualityError, match="won_amounts"):
        run_checks(db, run_id, report_path=tmp_path / "null.md")
