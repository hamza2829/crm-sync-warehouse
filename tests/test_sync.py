import json

import pytest

from pipeline.schemas import validate_records
from pipeline.sync import extract, load, sync, validate


def test_full_sync_and_incremental_noop(db, crm):
    sync(db, crm)
    before = db.rows("SELECT * FROM raw_deals ORDER BY id")
    second = sync(db, crm)
    assert len(before) == 500
    assert db.rows("SELECT * FROM raw_deals ORDER BY id") == before
    # Companies and contacts are small full snapshots; no deals are fetched again.
    assert (
        db.rows("SELECT rows_seen FROM sync_runs WHERE run_id = ?", (second,))[0]["rows_seen"]
        == 125
    )


def test_incremental_fetches_exactly_changed_record(db, crm, api):
    sync(db, crm)
    row = api.app.state.data["deals"][0]
    stage = "won" if row["stage"] != "won" else "lost"
    api.patch("/deals/1/stage", json={"stage": stage}).raise_for_status()
    batch = extract(db, crm)
    assert [r["id"] for r in batch["records"]["deals"]] == [1]
    load(db, validate(batch))
    assert db.rows("SELECT stage FROM raw_deals WHERE id=1")[0]["stage"] == stage


def test_reloading_full_snapshot_is_idempotent(db, crm):
    sync(db, crm)
    before = db.rows("SELECT * FROM raw_deals ORDER BY id")
    with db.connect() as connection:
        connection.execute("DELETE FROM sync_state")
    sync(db, crm)
    assert db.rows("SELECT * FROM raw_deals ORDER BY id") == before


def test_drift_quarantines_and_advances_cursor(db, crm):
    run = sync(db, crm, drift=True)
    assert db.rows("SELECT COUNT(*) AS n FROM raw_deals")[0]["n"] == 0
    rejected = db.rows("SELECT * FROM quarantine")
    assert len(rejected) == 500
    assert "amount" in rejected[0]["reason"] and "currency" in rejected[0]["reason"]
    assert db.cursor() is not None
    report = json.loads(db.rows("SELECT drift FROM sync_runs WHERE run_id=?", (run,))[0]["drift"])
    assert report["deals"]["unknown_fields"] == ["campaign_code", "value"]


def test_unknown_fields_preserved(db, crm, api):
    api.app.state.data["deals"][0]["ai_tag"] = "synthetic"
    sync(db, crm)
    assert (
        json.loads(db.rows("SELECT raw FROM raw_deals WHERE id=1")[0]["raw"])["ai_tag"]
        == "synthetic"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", -1),
        ("stage", "bad"),
        ("currency", "EUR"),
        ("updated_at", "not-a-time"),
        ("amount", "NaN"),
    ],
)
def test_bad_record_is_rejected_without_crash(api, field, value):
    row = dict(api.app.state.data["deals"][0])
    row[field] = value
    valid, rejected, _ = validate_records("deals", [row])
    assert not valid and len(rejected) == 1


def test_checkpoint_unchanged_when_load_fails(db, crm, monkeypatch):
    batch = validate(extract(db, crm))
    original = db.upsert
    calls = []

    def fail_after_first(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("simulated disk failure")
        original(*args)

    monkeypatch.setattr(db, "upsert", fail_after_first)
    with pytest.raises(RuntimeError):
        load(db, batch)
    assert db.cursor() is None
    assert db.rows("SELECT COUNT(*) AS n FROM raw_deals")[0]["n"] == 0


def test_stale_extracted_batch_cannot_regress_checkpoint(db, crm):
    old_batch = validate(extract(db, crm))
    sync(db, crm)
    with pytest.raises(ValueError, match="Checkpoint changed"):
        load(db, old_batch)


@pytest.mark.parametrize("field", ["id", "updated_at"])
def test_missing_cursor_fields_in_payload_do_not_crash_load(db, crm, field):
    batch = extract(db, crm)
    # The source envelope provides the checkpoint independently of record fields.
    batch["records"]["deals"][-1].pop(field)
    load(db, validate(batch))
    assert len(db.rows("SELECT * FROM quarantine")) == 1
    assert len(db.rows("SELECT * FROM raw_deals")) == 499
    assert extract(db, crm)["records"]["deals"] == []
