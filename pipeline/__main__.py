"""Plain Python CLI. Airflow is deliberately not a local dependency."""

import argparse
import logging
import os

import httpx

from pipeline.client import CRMClient
from pipeline.forecast import answer_pipeline_question
from pipeline.reporting import generate_report
from pipeline.storage import Database
from pipeline.sync import sync
from quality.checks import QualityError, run_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "demo", "sync", "answer"])
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--crm-url", default=os.getenv("CRM_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--drift", action="store_true", help="Request synthetic schema drift")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = Database(args.database_url)
    db.initialize()
    if args.command == "init":
        db.run_models()
        return
    if args.command == "answer":
        print(answer_pipeline_question(db))
        return
    if args.command == "demo":
        from fastapi.testclient import TestClient

        from mock_crm.app import create_app

        client = TestClient(create_app())
    else:
        client = httpx.Client(base_url=args.crm_url, timeout=15)
    with client:
        flags = {"drift": True} if args.drift else {}
        run_id = sync(db, CRMClient(client), **flags)
    db.run_models()
    try:
        run_checks(db, run_id)
    except QualityError:
        generate_report(db, run_id)
        raise
    dashboard = generate_report(db, run_id)
    print(f"Dashboard: {dashboard.resolve()}")
    print(answer_pipeline_question(db))


if __name__ == "__main__":
    main()
