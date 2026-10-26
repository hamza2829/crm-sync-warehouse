"""The agent-facing surface: three fixed SELECTs, no SQL argument."""

import re
from datetime import date

from pipeline.storage import Database


class ReadQueries:
    def __init__(self, database_url: str):
        self._db = Database(database_url)

    def funnel(self) -> list[dict]:
        return self._db.rows("SELECT * FROM model_funnel ORDER BY stage_order", readonly=True)

    def monthly_revenue(self, start: str, end: str) -> list[dict]:
        for month in (start, end):
            if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
                raise ValueError("Use YYYY-MM")
            date.fromisoformat(month + "-01")
        if start > end or int(end[:4]) - int(start[:4]) > 10:
            raise ValueError("Use an ordered range of at most ten years")
        return self._db.rows(
            """
            SELECT * FROM model_monthly_revenue WHERE month >= ? AND month <= ? ORDER BY month
            """,
            (start, end),
            readonly=True,
        )

    def deal_history(self, deal_id: int, limit: int = 100) -> list[dict]:
        if (
            type(deal_id) is not int
            or deal_id < 1
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError("Use a positive integer deal id and a limit of 1..1000")
        return self._db.rows(
            """
            SELECT * FROM stg_deal_events WHERE deal_id=? ORDER BY event_time, event_id LIMIT ?
            """,
            (deal_id, limit),
            readonly=True,
        )
