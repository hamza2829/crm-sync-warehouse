"""Run with: python -m uvicorn mock_crm.app:app --port 8000."""

import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from mock_crm.data import STAGES, cursor_for, decode_cursor, make_data

Stage = Enum("Stage", {value: value for value in STAGES}, type=str)


class StageChange(BaseModel):
    stage: Stage


def create_app(data: dict | None = None, clock=time.monotonic) -> FastAPI:
    app = FastAPI(title="Synthetic mock CRM", description="No real CRM connection")
    app.state.data = data if data is not None else make_data()
    requests = deque()
    lock = threading.Lock()

    @app.get("/health")
    def health():
        return {"status": "ok", "synthetic": True}

    @app.get("/deals")
    def deals(
        after: str | None = None,
        limit: int = Query(100, ge=1, le=200),
        drift: bool | None = None,
        rate_limit: int | None = Query(None, ge=0),
    ):
        quota = rate_limit if rate_limit is not None else int(os.getenv("CRM_RATE_LIMIT", "0"))
        with lock:
            current = clock()
            while requests and requests[0] <= current - 60:
                requests.popleft()
            if quota:
                if len(requests) >= quota:
                    delay = max(1, int(60 - (current - requests[0])) + 1)
                    raise HTTPException(
                        429, "Mock quota exceeded", headers={"Retry-After": str(delay)}
                    )
                requests.append(current)
        try:
            boundary = decode_cursor(after) if after else ("", 0)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        records = sorted(app.state.data["deals"], key=lambda d: (d["updated_at"], d["id"]))
        records = [d for d in records if (d["updated_at"], d["id"]) > boundary]
        page = [dict(row) for row in records[:limit]]
        checkpoint = cursor_for(page[-1]) if page else after
        next_cursor = cursor_for(page[-1]) if page and len(records) > limit else None
        enabled = drift if drift is not None else os.getenv("CRM_SCHEMA_DRIFT", "0") == "1"
        if enabled:
            for row in page:
                row["value"] = row.pop("amount")
                row.pop("currency")
                row["campaign_code"] = "synthetic-drift"
        return {
            "results": page,
            "checkpoint": checkpoint,
            "paging": {"next": {"after": next_cursor}} if next_cursor else {},
        }

    @app.get("/companies")
    def companies():
        return {"results": app.state.data["companies"]}

    @app.get("/contacts")
    def contacts():
        return {"results": app.state.data["contacts"]}

    @app.patch("/deals/{deal_id}/stage")
    def change_stage(deal_id: int, change: StageChange):
        with lock:
            deal = next((d for d in app.state.data["deals"] if d["id"] == deal_id), None)
            if deal is None:
                raise HTTPException(404, "Unknown deal")
            if deal["stage"] == change.stage.value:
                return {"changed": False}
            stamp = datetime.now(UTC).isoformat()
            event = {
                "event_id": str(uuid4()),
                "deal_id": deal_id,
                "event_time": stamp,
                "old_stage": deal["stage"],
                "new_stage": change.stage.value,
            }
            url = os.getenv("CRM_WEBHOOK_URL")
            if url:
                headers = {"X-Webhook-Secret": os.getenv("WEBHOOK_SECRET", "demo-secret")}
                try:
                    # An injected client lets tests exercise real endpoints without networking.
                    client = getattr(app.state, "webhook_client", None)
                    if client is not None:
                        client.post(url, json=event, headers=headers).raise_for_status()
                    else:
                        with httpx.Client(timeout=10) as client:
                            client.post(url, json=event, headers=headers).raise_for_status()
                except httpx.HTTPError as exc:
                    raise HTTPException(
                        502, "Webhook delivery failed; retry the stage change"
                    ) from exc
            deal.update(stage=change.stage.value, updated_at=stamp)
            return {"changed": True, "event": event, "webhook_delivered": bool(url)}

    return app


app = create_app()
