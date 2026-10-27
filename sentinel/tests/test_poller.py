import pytest

from innerlogic_sentinel.client import Page
from innerlogic_sentinel.errors import IngestionError, RetryableError
from innerlogic_sentinel.poller import run_once


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def fetch_page(self, *, cursor, start_utc, limit):
        self.requests.append((cursor, start_utc, limit))
        item = self.pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeStore:
    def __init__(self, cursor=None):
        self.cursor = cursor
        self.saves = []

    def get(self):
        return self.cursor

    def save(self, cursor):
        self.saves.append(cursor)
        self.cursor = cursor


class FakeSink:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []

    def upload(self, rows):
        if self.fail:
            raise IngestionError("rejected")
        self.uploads.append(list(rows))


def ev(i):
    return {"eventId": f"e{i}", "sequence": str(i), "occurredAt": "2026-09-01T00:00:00Z",
            "recordedAt": "2026-09-01T00:00:01Z", "tenantId": "t", "category": "x",
            "action": "a", "outcome": "SUCCESS"}


def run(client, store, sink, **kw):
    return run_once(client, store, sink, start_utc="S", page_limit=500,
                    max_runtime_seconds=kw.pop("budget", 1000), **kw)


def test_first_run_uses_start_then_cursor_and_saves_each_page():
    client = FakeClient([Page([ev(1)], "c1", True), Page([ev(2)], "c2", False)])
    store, sink = FakeStore(), FakeSink()
    stats = run(client, store, sink)
    assert client.requests == [(None, "S", 500), ("c1", "S", 500)]
    assert store.saves == ["c1", "c2"]
    assert stats.pages == 2 and stats.events == 2 and stats.caught_up


def test_resumes_from_saved_cursor():
    client = FakeClient([Page([], "c9", False)])
    store = FakeStore("c5")
    run(client, store, FakeSink())
    assert client.requests[0][0] == "c5"


def test_cursor_not_saved_when_upload_fails():
    client = FakeClient([Page([ev(1)], "c1", False)])
    store = FakeStore("c0")
    with pytest.raises(IngestionError):
        run(client, store, FakeSink(fail=True))
    assert store.saves == [] and store.cursor == "c0"


def test_failure_on_second_page_keeps_first_page_checkpoint():
    client = FakeClient([Page([ev(1)], "c1", True), RetryableError("boom")])
    store = FakeStore()
    with pytest.raises(RetryableError):
        run(client, store, FakeSink())
    assert store.saves == ["c1"]


def test_empty_page_still_saves_cursor_and_skips_upload():
    client = FakeClient([Page([], "c1", False)])
    store, sink = FakeStore(), FakeSink()
    run(client, store, sink)
    assert store.saves == ["c1"] and sink.uploads == []


def test_stops_at_time_budget_and_resumes_later():
    ticks = iter([0, 500])  # 1st: deadline = 0+100; 2nd: after page 1 -> over budget
    client = FakeClient([Page([ev(1)], "c1", True), Page([ev(2)], "c2", False)])
    store = FakeStore()
    stats = run(client, store, FakeSink(), budget=100, clock=lambda: next(ticks))
    assert stats.pages == 1 and not stats.caught_up and store.cursor == "c1"


def test_guards_against_empty_has_more_loop():
    client = FakeClient([Page([], "c1", True)])
    store = FakeStore("c1")
    stats = run(client, store, FakeSink())
    assert stats.pages == 1 and len(client.requests) == 1
