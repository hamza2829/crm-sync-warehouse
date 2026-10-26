"""A small authenticated, replay-safe stage event receiver."""

import os
import secrets

from fastapi import FastAPI, Header, HTTPException

from pipeline.schemas import DealEvent
from pipeline.storage import Database, utc_now


def create_app(db: Database | None = None) -> FastAPI:
    app = FastAPI(title="Synthetic CRM stage event receiver")

    @app.post("/webhooks/deals")
    def receive(event: DealEvent, x_webhook_secret: str = Header("")):
        expected = os.getenv("WEBHOOK_SECRET", "demo-secret")
        if not expected or not secrets.compare_digest(expected, x_webhook_secret):
            raise HTTPException(401, "Invalid webhook secret")
        database = db or Database()
        # Initialize separately via CLI before serving; never migrate per request.
        with database.connect() as connection:
            database.execute(
                connection,
                """
                INSERT INTO deal_events VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_time, event_id) DO NOTHING
                """,
                (
                    str(event.event_id),
                    event.event_time.isoformat(),
                    event.deal_id,
                    event.old_stage,
                    event.new_stage,
                    utc_now(),
                ),
            )
        return {"accepted": True}

    return app


app = create_app()
