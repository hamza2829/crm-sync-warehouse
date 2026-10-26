import sqlite3

import pytest

from pipeline.queries import ReadQueries
from pipeline.sync import sync


@pytest.fixture
def reader(db, crm):
    sync(db, crm)
    db.run_models()
    return ReadQueries(db.url)


def test_funnel_and_monthly_totals(reader, db):
    funnel = reader.funnel()
    assert funnel[0]["reached_deals"] == 500
    assert sum(row["current_deals"] for row in funnel) == 500
    assert all(0 <= row["conversion_rate"] <= 1 for row in funnel)
    monthly = reader.monthly_revenue("2000-01", "2009-12")
    assert monthly == []
    total = db.rows("SELECT SUM(amount) AS n FROM raw_deals WHERE stage='won'")[0]["n"]
    assert db.rows("SELECT SUM(won_revenue) AS n FROM model_monthly_revenue")[0]["n"] == total


def test_models_can_be_run_again(reader, db):
    before = reader.funnel()
    db.run_models()
    assert reader.funnel() == before


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-13", "2026-14"),
        ("2026-01' OR 1=1", "2026-12"),
        ("2027-01", "2026-01"),
        ("2000-01", "2020-01"),
        (None, "2026-01"),
    ],
)
def test_month_input_validation(db, start, end):
    with pytest.raises(ValueError):
        ReadQueries(db.url).monthly_revenue(start, end)


@pytest.mark.parametrize(
    "deal_id,limit", [("1 OR 1=1", 1), (-1, 10), (True, 10), (1, 0), (1, 1001)]
)
def test_history_input_validation(db, deal_id, limit):
    with pytest.raises(ValueError):
        ReadQueries(db.url).deal_history(deal_id, limit)


def test_readonly_connection_rejects_writes(reader, db):
    with db.connect(readonly=True) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM raw_deals")
    assert reader.deal_history(1) == []
