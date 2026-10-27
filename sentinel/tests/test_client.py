import pytest
import requests

from innerlogic_sentinel.client import AuditApiClient, parse_page
from innerlogic_sentinel.errors import NonRetryableError, RetryableError, ValidationError

GOOD = {"events": [{"eventId": "e1"}], "nextCursor": "c1", "hasMore": False}


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, bad_json=False):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("bad json")
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(session, **kw):
    sleeps = []
    client = AuditApiClient(
        "https://api.example.com/", "ilaudit_secret", session=session,
        sleep=sleeps.append, rng=lambda: 0.5, **kw,
    )
    return client, sleeps


def test_first_request_uses_from_not_cursor():
    s = FakeSession(FakeResponse(body=GOOD))
    client, _ = make(s)
    client.fetch_page(cursor=None, start_utc="2026-09-01T00:00:00.000Z", limit=500)
    p = s.calls[0]["params"]
    assert p == {"from": "2026-09-01T00:00:00.000Z", "limit": 500}
    assert s.calls[0]["url"] == "https://api.example.com/api/v1/audit-events"
    assert s.calls[0]["headers"]["Authorization"] == "Bearer ilaudit_secret"


def test_later_request_uses_cursor_never_both():
    s = FakeSession(FakeResponse(body=GOOD))
    client, _ = make(s)
    client.fetch_page(cursor="abc", start_utc="2026-09-01T00:00:00.000Z", limit=100)
    assert s.calls[0]["params"] == {"cursor": "abc", "limit": 100}


def test_429_honours_retry_after():
    s = FakeSession(FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(body=GOOD))
    client, sleeps = make(s)
    page = client.fetch_page(cursor="c", start_utc=None, limit=10)
    assert page.next_cursor == "c1"
    assert sleeps == [7.0]


def test_5xx_backs_off_with_jitter_then_succeeds():
    s = FakeSession(FakeResponse(503), FakeResponse(500), FakeResponse(body=GOOD))
    client, sleeps = make(s)
    client.fetch_page(cursor="c", start_utc=None, limit=10)
    assert sleeps == [0.5 * 1, 0.5 * 2]  # rng=0.5 -> half of the exponential ceiling


def test_timeout_and_connection_errors_retry():
    s = FakeSession(requests.Timeout(), requests.ConnectionError(), FakeResponse(body=GOOD))
    client, sleeps = make(s)
    assert client.fetch_page(cursor="c", start_utc=None, limit=10).has_more is False
    assert len(sleeps) == 2


def test_truncated_body_is_retried():
    s = FakeSession(FakeResponse(bad_json=True), FakeResponse(body=GOOD))
    client, _ = make(s)
    assert client.fetch_page(cursor="c", start_utc=None, limit=10).next_cursor == "c1"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_fail_fast_without_retry(status):
    s = FakeSession(FakeResponse(status))
    client, sleeps = make(s)
    with pytest.raises(NonRetryableError) as exc:
        client.fetch_page(cursor="c", start_utc=None, limit=10)
    assert len(s.calls) == 1 and sleeps == []
    assert "ilaudit_secret" not in str(exc.value)


def test_gives_up_after_max_attempts():
    s = FakeSession(*[FakeResponse(503) for _ in range(3)])
    client, sleeps = make(s, max_attempts=3)
    with pytest.raises(RetryableError):
        client.fetch_page(cursor="c", start_utc=None, limit=10)
    assert len(s.calls) == 3 and len(sleeps) == 2


@pytest.mark.parametrize("body", [
    [], {"events": "x", "nextCursor": "c", "hasMore": False},
    {"events": [1], "nextCursor": "c", "hasMore": False},
    {"events": [], "hasMore": False},
    {"events": [], "nextCursor": "c", "hasMore": "no"},
])
def test_parse_page_rejects_bad_shapes(body):
    with pytest.raises(ValidationError):
        parse_page(body)


def test_parse_page_accepts_empty_page_and_unknown_fields():
    page = parse_page({"schemaVersion": "1.0", "events": [], "nextCursor": "c", "hasMore": False, "extra": 1})
    assert page.events == [] and page.next_cursor == "c"
