from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from pipeline.storage import utc_now
from pipeline.webhook import create_app


def event():
    return {
        "event_id": str(uuid4()),
        "deal_id": 1,
        "event_time": utc_now(),
        "old_stage": "lead",
        "new_stage": "won",
    }


def test_webhook_authentication_and_validation(db):
    with TestClient(create_app(db)) as receiver:
        assert receiver.post("/webhooks/deals", json=event()).status_code == 401
        assert (
            receiver.post(
                "/webhooks/deals",
                json={"deal_id": "bad"},
                headers={"X-Webhook-Secret": "demo-secret"},
            ).status_code
            == 422
        )
    assert db.rows("SELECT * FROM deal_events") == []


def test_webhook_replay_is_idempotent(db):
    payload = event()
    with TestClient(create_app(db)) as receiver:
        for _ in range(2):
            receiver.post(
                "/webhooks/deals", json=payload, headers={"X-Webhook-Secret": "demo-secret"}
            ).raise_for_status()
    assert len(db.rows("SELECT * FROM deal_events")) == 1


def test_stage_change_delivers_webhook(db, api, monkeypatch):
    monkeypatch.setenv("CRM_WEBHOOK_URL", "/webhooks/deals")
    with TestClient(create_app(db)) as receiver:
        api.app.state.webhook_client = receiver
        before = api.app.state.data["deals"][0]["stage"]
        stage = "won" if before != "won" else "lost"
        result = api.patch("/deals/1/stage", json={"stage": stage})
        result.raise_for_status()
        assert result.json()["webhook_delivered"]
    row = db.rows("SELECT * FROM deal_events")[0]
    assert row["old_stage"] == before and row["new_stage"] == stage


def test_same_stage_does_not_emit_event(api):
    before = api.app.state.data["deals"][0]["stage"]
    assert api.patch("/deals/1/stage", json={"stage": before}).json() == {"changed": False}


def test_failed_delivery_does_not_change_stage(api, monkeypatch):
    monkeypatch.setenv("CRM_WEBHOOK_URL", "http://receiver/webhooks/deals")
    before = api.app.state.data["deals"][0]["stage"]
    target = "won" if before != "won" else "lost"
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as receiver:
        api.app.state.webhook_client = receiver
        assert api.patch("/deals/1/stage", json={"stage": target}).status_code == 502
    assert api.app.state.data["deals"][0]["stage"] == before
