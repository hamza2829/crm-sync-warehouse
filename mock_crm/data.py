"""A deterministic seed with 500 deals across the last 12 complete months."""

import base64
import json
import random
from datetime import UTC, datetime, timedelta

STAGES = ("lead", "qualified", "proposal", "won", "lost")


def month_start(value: datetime, offset: int = 0) -> datetime:
    index = value.year * 12 + value.month - 1 + offset
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC)


def make_data(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rng = random.Random(42)
    companies = [
        {
            "id": i,
            "name": f"Synthetic Company {i}",
            "industry": "demo",
            "updated_at": now.isoformat(),
        }
        for i in range(1, 26)
    ]
    contacts = [
        {
            "id": i,
            "company_id": (i - 1) % 25 + 1,
            "email": f"person{i}@example.invalid",
            "updated_at": now.isoformat(),
        }
        for i in range(1, 101)
    ]
    deals = []
    for i in range(1, 501):
        close = month_start(now, -12 + (i - 1) % 12) + timedelta(days=(i - 1) % 27)
        created = close - timedelta(days=30)
        deals.append(
            {
                "id": i,
                "name": f"Synthetic Deal {i}",
                "company_id": (i - 1) % 25 + 1,
                "contact_id": (i - 1) % 100 + 1,
                "stage": rng.choices(STAGES, weights=[20, 20, 20, 30, 10])[0],
                "amount": rng.randrange(10, 200) * 100,
                "currency": "USD",
                "created_at": created.isoformat(),
                "updated_at": now.isoformat(),
                "close_date": close.date().isoformat(),
            }
        )
    return {"companies": companies, "contacts": contacts, "deals": deals}


def cursor_for(record: dict) -> str:
    payload = json.dumps([record["updated_at"], record["id"]], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        stamp, record_id = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or type(record_id) is not int or record_id < 1:
            raise ValueError
        return parsed.astimezone(UTC).isoformat(), record_id
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Invalid cursor") from exc
