"""The same small Python steps, orchestrated only in GitHub Actions."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from airflow.sdk import dag, task

from pipeline.client import CRMClient
from pipeline.forecast import forecast_from_models
from pipeline.reporting import generate_report
from pipeline.storage import Database, json_text
from pipeline.sync import extract, load, validate
from quality.checks import run_checks


@dag(
    dag_id="crm_sync",
    schedule="@daily",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["synthetic", "crm"],
)
def crm_sync():
    @task(task_id="extract")
    def extract_task():
        db = Database()
        db.initialize()
        with httpx.Client(
            base_url=os.getenv("CRM_URL", "http://127.0.0.1:8000"), timeout=15
        ) as client:
            batch = extract(db, CRMClient(client))
        folder = Path("artifacts/runs") / batch["run_id"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "extracted.json"
        path.write_text(json_text(batch), encoding="utf-8")
        return str(path.resolve())

    @task(task_id="validate")
    def validate_task(path: str):
        batch = validate(json.loads(Path(path).read_text(encoding="utf-8")))
        target = Path(path).with_name("validated.json")
        target.write_text(json_text(batch), encoding="utf-8")
        return str(target)

    @task(task_id="load")
    def load_task(path: str):
        return load(Database(), json.loads(Path(path).read_text(encoding="utf-8")))

    @task(task_id="run_models")
    def run_models_task(sync_run_id: str):
        Database().run_models()
        return sync_run_id

    @task(task_id="data_quality_checks")
    def quality_task(sync_run_id: str):
        run_checks(Database(), sync_run_id)
        return sync_run_id

    @task(task_id="forecast")
    def forecast_task(sync_run_id: str):
        projection = forecast_from_models(Database())
        path = Path("artifacts/runs") / sync_run_id / "forecast.json"
        path.write_text(json_text(projection), encoding="utf-8")

    @task(task_id="report", trigger_rule="all_done")
    def report_task(sync_run_id: str):
        result = generate_report(Database(), sync_run_id)
        # A successful all_done leaf would otherwise mask a failed quality task.
        checks = Database().rows(
            "SELECT passed FROM quality_results WHERE run_id=?", (sync_run_id,)
        )
        if len(checks) != 5 or not all(row["passed"] for row in checks):
            raise RuntimeError("Quality failed; failure report saved")
        if not (Path("artifacts/runs") / sync_run_id / "forecast.json").exists():
            raise RuntimeError("Forecast task failed; diagnostic report saved")
        return str(result.resolve())

    batch = extract_task()
    validated = validate_task(batch)
    run = load_task(validated)
    modeled = run_models_task(run)
    checked = quality_task(modeled)
    projection = forecast_task(checked)
    report = report_task(run)
    projection >> report


crm_sync()
