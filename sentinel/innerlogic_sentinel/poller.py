from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Protocol

from .client import Page
from .ingest import to_row

log = logging.getLogger(__name__)


class PageSource(Protocol):
    def fetch_page(self, *, cursor: Optional[str], start_utc: Optional[str], limit: int) -> Page: ...


class CheckpointStore(Protocol):
    def get(self) -> Optional[str]: ...
    def save(self, cursor: str) -> None: ...


class Sink(Protocol):
    def upload(self, rows: Iterable[Dict[str, Any]]) -> None: ...


@dataclass
class RunStats:
    pages: int = 0
    events: int = 0
    caught_up: bool = False


def run_once(
    client: PageSource,
    store: CheckpointStore,
    sink: Sink,
    *,
    start_utc: str,
    page_limit: int,
    max_runtime_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> RunStats:
    """Poll until caught up or the time budget is spent.

    Order per page (this ordering is the delivery guarantee):
      1. fetch and validate
      2. upload every event to Azure
      3. only then persist nextCursor
    Any failure in 1-2 raises with the previous checkpoint intact, so the
    next run replays the page (at-least-once; dedupe on EventId downstream).
    """
    stats = RunStats()
    cursor = store.get()
    deadline = clock() + max_runtime_seconds

    while True:
        page = client.fetch_page(cursor=cursor, start_utc=start_utc, limit=page_limit)

        if page.events:
            sink.upload([to_row(e) for e in page.events])

        # An empty page can still carry a valid cursor; save it too.
        store.save(page.next_cursor)

        stats.pages += 1
        stats.events += len(page.events)
        no_progress = page.next_cursor == cursor and not page.events
        cursor = page.next_cursor

        if not page.has_more:
            stats.caught_up = True
            break
        if no_progress:
            log.warning("API reported hasMore with an empty page and unchanged cursor; stopping")
            break
        if clock() >= deadline:
            log.info("Time budget reached; remaining pages will be fetched on the next run")
            break

    log.info("Run complete: %d page(s), %d event(s), caught_up=%s",
             stats.pages, stats.events, stats.caught_up)
    return stats
