"""Extract, validate and atomically load. Cursor progress includes quarantined rows."""

import logging
from uuid import uuid4

from mock_crm.data import cursor_for
from pipeline.client import CRMClient
from pipeline.schemas import validate_records
from pipeline.storage import Database, json_text, utc_now

logger = logging.getLogger(__name__)


def extract(db: Database, client: CRMClient, **flags) -> dict:
    start_cursor = db.cursor()
    return {
        "run_id": str(uuid4()),
        "started_at": utc_now(),
        "start_cursor": start_cursor,
        "records": {
            "deals": client.deals(start_cursor, **flags),
            "companies": client.get("/companies")["results"],
            "contacts": client.get("/contacts")["results"],
        },
    }


def validate(batch: dict) -> dict:
    valid, rejected, drift = {}, [], {}
    for resource, records in batch["records"].items():
        valid[resource], invalid, drift[resource] = validate_records(resource, records)
        rejected.extend(invalid)
    return {**batch, "valid": valid, "rejected": rejected, "drift": drift}


def load(db: Database, batch: dict) -> str:
    stamp = utc_now()
    with db.connect() as connection:
        # One writer at a time. Reject a batch extracted from an obsolete checkpoint.
        if db.postgres:
            connection.execute("SELECT pg_advisory_xact_lock(1942001)")
        else:
            connection.execute("BEGIN IMMEDIATE")
        state = db.execute(
            connection, "SELECT cursor FROM sync_state WHERE resource = ?", ("deals",)
        ).fetchone()
        actual = state["cursor"] if state else None
        if actual != batch["start_cursor"]:
            raise ValueError("Checkpoint changed; extract again")
        for resource, records in batch["valid"].items():
            for record in records:
                db.upsert(connection, resource, record["parsed"], record["raw"])
        for rejected in batch["rejected"]:
            db.execute(
                connection,
                """
                INSERT INTO quarantine VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, resource, record_id)
                DO UPDATE SET reason=excluded.reason, raw=excluded.raw
                """,
                (
                    batch["run_id"],
                    rejected["resource"],
                    str(rejected["raw"].get("id", "unknown")),
                    rejected["reason"],
                    json_text(rejected["raw"]),
                    stamp,
                ),
            )
        records = batch["records"]["deals"]
        if records:
            cursor = cursor_for(records[-1])
            db.execute(
                connection,
                """
                INSERT INTO sync_state VALUES (?, ?, ?) ON CONFLICT (resource)
                DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at
                """,
                ("deals", cursor, stamp),
            )
        count = db.execute(connection, "SELECT COUNT(*) AS n FROM raw_deals").fetchone()["n"]
        db.execute(
            connection,
            "INSERT INTO sync_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                batch["run_id"],
                batch["started_at"],
                sum(len(r) for r in batch["records"].values()),
                sum(len(r) for r in batch["valid"].values()),
                len(batch["rejected"]),
                count,
                json_text(batch["drift"]),
            ),
        )
    logger.info("run=%s drift=%s", batch["run_id"], json_text(batch["drift"]))
    return batch["run_id"]


def sync(db: Database, client: CRMClient, **flags) -> str:
    return load(db, validate(extract(db, client, **flags)))
