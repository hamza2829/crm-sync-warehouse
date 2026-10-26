import json
from datetime import UTC, datetime
from pathlib import Path

from pipeline.storage import Database, json_text, utc_now


class QualityError(RuntimeError):
    pass


def evaluate(
    metrics: dict, *, freshness_hours=48, count_tolerance=0.2, quarantine_limit=0.05
) -> list[dict]:
    """Pure decision logic, independent of either SQL database."""
    previous = metrics["previous_count"]
    count_ok = metrics["row_count"] > 0
    if previous is not None:
        count_ok = count_ok and previous * (1 - count_tolerance) <= metrics[
            "row_count"
        ] <= previous * (1 + count_tolerance)
    specs = [
        (
            "unique_ids",
            metrics["duplicate_ids"] == 0,
            metrics["duplicate_ids"],
            "0 duplicate ids across raw tables",
        ),
        (
            "won_amounts",
            metrics["won_null_amounts"] == 0,
            metrics["won_null_amounts"],
            "0 won deals with NULL amount",
        ),
        (
            "row_count",
            count_ok,
            {"current": metrics["row_count"], "previous": previous},
            f"positive and within {count_tolerance:.0%} of previous run",
        ),
        (
            "freshness",
            metrics["age_hours"] is not None and -0.1 <= metrics["age_hours"] <= freshness_hours,
            metrics["age_hours"],
            f"newest source update within {freshness_hours} hours",
        ),
        (
            "quarantine_rate",
            metrics["quarantine_rate"] < quarantine_limit,
            metrics["quarantine_rate"],
            f"each resource below {quarantine_limit:.0%} rejected in this run",
        ),
    ]
    return [
        {
            "check_name": name,
            "passed": bool(passed),
            "observed": observed,
            "expectation": expectation,
        }
        for name, passed, observed, expectation in specs
    ]


def collect_metrics(db: Database, run_id: str, now: datetime | None = None) -> dict:
    run = db.rows("SELECT * FROM sync_runs WHERE run_id=?", (run_id,))[0]
    previous = db.rows(
        """
        SELECT row_count FROM sync_runs WHERE started_at < ?
        ORDER BY started_at DESC LIMIT 1
        """,
        (run["started_at"],),
    )
    duplicates = sum(
        db.rows(f"SELECT COUNT(*) - COUNT(DISTINCT id) AS n FROM {table}")[0]["n"]
        for table in ("raw_deals", "raw_companies", "raw_contacts")
    )
    newest = db.rows("SELECT MAX(updated_at) AS newest FROM raw_deals")[0]["newest"]
    if isinstance(newest, str):
        newest = datetime.fromisoformat(newest)
    drift = run["drift"] if isinstance(run["drift"], dict) else json.loads(run["drift"])
    rate = max(
        (entry["rejected"] / entry["seen"] if entry["seen"] else 0 for entry in drift.values()),
        default=0,
    )
    return {
        "duplicate_ids": duplicates,
        "won_null_amounts": db.rows(
            "SELECT COUNT(*) AS n FROM raw_deals WHERE stage='won' AND amount IS NULL"
        )[0]["n"],
        "row_count": db.rows("SELECT COUNT(*) AS n FROM raw_deals")[0]["n"],
        "previous_count": previous[0]["row_count"] if previous else None,
        "age_hours": ((now or datetime.now(UTC)) - newest).total_seconds() / 3600
        if newest
        else None,
        "quarantine_rate": rate,
    }


def quality_markdown(db: Database, run_id: str) -> str:
    run = db.rows("SELECT * FROM sync_runs WHERE run_id=?", (run_id,))[0]
    rows = db.rows("SELECT * FROM quality_results WHERE run_id=? ORDER BY check_name", (run_id,))
    lines = [
        "# Last run report",
        "",
        f"Run: `{run_id}`",
        f"Started (UTC): {run['started_at']}",
        f"Records seen: {run['rows_seen']}; loaded: {run['rows_loaded']}; "
        f"quarantined: {run['quarantined']}.",
        "",
        "Synthetic data from a mock CRM. All money is USD.",
        "",
        "| Check | Status | Observed | Expectation |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['check_name']} | {'PASS' if row['passed'] else 'FAIL'} | "
            f"{row['observed']} | {row['expectation']} |"
        )
    drift = run["drift"] if isinstance(run["drift"], dict) else json.loads(run["drift"])
    lines.extend(
        ["", "Drift report:", "", "```json", json.dumps(drift, indent=2, sort_keys=True), "```", ""]
    )
    return "\n".join(lines)


def run_checks(
    db: Database, run_id: str, *, report_path: str | Path = "docs/last_run_report.md", **thresholds
) -> list[dict]:
    results = evaluate(collect_metrics(db, run_id), **thresholds)
    with db.connect() as connection:
        for row in results:
            db.execute(
                connection,
                """
                INSERT INTO quality_results VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, check_name) DO UPDATE SET
                    passed=excluded.passed, observed=excluded.observed,
                    expectation=excluded.expectation, checked_at=excluded.checked_at
                """,
                (
                    run_id,
                    row["check_name"],
                    row["passed"],
                    json_text(row["observed"]),
                    row["expectation"],
                    utc_now(),
                ),
            )
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(quality_markdown(db, run_id), encoding="utf-8")
    failed = [row["check_name"] for row in results if not row["passed"]]
    if failed:
        raise QualityError("Failed data quality: " + ", ".join(failed))
    return results
