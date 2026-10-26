"""Bounded retries for read requests. Never retry a non-transient 4xx."""

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


def retry_delay(header: str | None, attempt: int, now: datetime | None = None) -> float:
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            try:
                return max(
                    0.0,
                    (parsedate_to_datetime(header) - (now or datetime.now(UTC))).total_seconds(),
                )
            except (ValueError, TypeError, OverflowError):
                pass
    return min(2**attempt, 30)


class CRMClient:
    def __init__(self, client: httpx.Client, *, attempts: int = 4, sleep=time.sleep):
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self.client, self.attempts, self.sleep = client, attempts, sleep

    def get(self, path: str, **params) -> dict:
        for attempt in range(self.attempts):
            try:
                response = self.client.get(path, params=params)
            except httpx.TransportError:
                if attempt == self.attempts - 1:
                    raise
                self.sleep(retry_delay(None, attempt))
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.attempts - 1:
                self.sleep(retry_delay(response.headers.get("Retry-After"), attempt))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("Unreachable retry state")

    def deals(self, after: str | None = None, **flags) -> list[dict]:
        records = []
        seen = set()
        while True:
            params = {"limit": 100, **flags}
            if after:
                params["after"] = after
            page = self.get("/deals", **params)
            records.extend(page["results"])
            following = page.get("paging", {}).get("next", {}).get("after")
            if not following:
                return records
            if following == after or following in seen:
                raise ValueError("CRM returned a repeated cursor")
            seen.add(following)
            after = following
