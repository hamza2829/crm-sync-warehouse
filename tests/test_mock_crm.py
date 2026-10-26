from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from mock_crm.app import create_app
from mock_crm.data import cursor_for, decode_cursor, make_data


def test_seed_is_deterministic_and_has_twelve_months():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    data = make_data(now)
    assert data == make_data(now)
    assert len(data["deals"]) == 500
    assert len({d["close_date"][:7] for d in data["deals"]}) == 12
    assert max(d["close_date"][:7] for d in data["deals"]) == "2026-09"


def test_pagination_orders_timestamp_ties_by_id(api):
    first = api.get("/deals", params={"limit": 2}).json()
    second = api.get(
        "/deals", params={"limit": 2, "after": first["paging"]["next"]["after"]}
    ).json()
    assert [d["id"] for d in first["results"] + second["results"]] == [1, 2, 3, 4]


@pytest.mark.parametrize("limit", [0, 201, -1])
def test_invalid_page_size(api, limit):
    assert api.get("/deals", params={"limit": limit}).status_code == 422


@pytest.mark.parametrize("cursor", ["garbage", "e30=", "W10=", "WyJub3QtYS1kYXRlIiwxXQ=="])
def test_invalid_cursor(api, cursor):
    assert api.get("/deals", params={"after": cursor}).status_code == 422


def test_cursor_roundtrip(api):
    row = api.get("/deals").json()["results"][0]
    assert decode_cursor(cursor_for(row)) == (row["updated_at"], row["id"])


def test_rate_limit_and_window_expiry():
    ticks = [100.0]
    with TestClient(create_app(clock=lambda: ticks[0])) as client:
        assert client.get("/deals?rate_limit=1").status_code == 200
        blocked = client.get("/deals?rate_limit=1")
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 60
        ticks[0] += 61
        assert client.get("/deals?rate_limit=1").status_code == 200


def test_drift_switch(api):
    row = api.get("/deals?drift=true").json()["results"][0]
    assert "amount" not in row and "currency" not in row
    assert "value" in row and "campaign_code" in row
    assert "amount" in api.get("/deals?drift=false").json()["results"][0]


def test_reference_endpoints(api):
    assert len(api.get("/companies").json()["results"]) == 25
    assert len(api.get("/contacts").json()["results"]) == 100


def test_environment_failure_switches(api, monkeypatch):
    monkeypatch.setenv("CRM_SCHEMA_DRIFT", "1")
    monkeypatch.setenv("CRM_RATE_LIMIT", "1")
    assert "value" in api.get("/deals").json()["results"][0]
    assert api.get("/deals").status_code == 429


def test_unknown_deal_and_invalid_stage(api):
    assert api.patch("/deals/9999/stage", json={"stage": "won"}).status_code == 404
    assert api.patch("/deals/1/stage", json={"stage": "invented"}).status_code == 422
