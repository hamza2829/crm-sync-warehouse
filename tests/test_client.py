from datetime import UTC, datetime

import httpx
import pytest

from pipeline.client import CRMClient, retry_delay


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_error_retries_and_respects_header(status):
    calls, sleeps = [], []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status if len(calls) == 1 else 200, headers={"Retry-After": "2"}, json={"results": []}
        )

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="http://mock") as client:
        assert CRMClient(client, sleep=sleeps.append).get("/deals") == {"results": []}
    assert len(calls) == 2 and sleeps == [2.0]


def test_http_date_retry_after():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    assert retry_delay("Mon, 26 Oct 2026 00:00:07 GMT", 0, now) == 7


@pytest.mark.parametrize("header", [None, "bad", "-1"])
def test_backoff_fallback_and_nonnegative_delay(header):
    assert retry_delay(header, 2) == (0 if header == "-1" else 4)


def test_retry_exhaustion_is_bounded():
    sleeps = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429)), base_url="http://mock"
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            CRMClient(client, attempts=3, sleep=sleeps.append).get("/deals")
    assert sleeps == [1, 2]


def test_no_retry_on_bad_request():
    sleeps = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(400)), base_url="http://mock"
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            CRMClient(client, sleep=sleeps.append).get("/deals")
    assert sleeps == []


def test_transport_failure_is_retried():
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("synthetic disconnect", request=request)
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="http://mock") as client:
        assert CRMClient(client, sleep=lambda _: None).get("/deals") == {}
    assert len(calls) == 2


def test_pagination_loop_is_rejected():
    page = {"results": [], "paging": {"next": {"after": "same"}}}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page)),
        base_url="http://mock",
    ) as client:
        with pytest.raises(ValueError, match="repeated cursor"):
            CRMClient(client).deals()
