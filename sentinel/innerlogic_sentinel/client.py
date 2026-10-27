from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

from .errors import NonRetryableError, RetryableError, ValidationError

log = logging.getLogger(__name__)

AUDIT_PATH = "/api/v1/audit-events"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 60.0


@dataclass(frozen=True)
class Page:
    events: List[Dict[str, Any]]
    next_cursor: str
    has_more: bool


def parse_page(body: Any) -> Page:
    """Validate the documented top-level shape; keep events untouched.

    Unknown fields, categories and actions are preserved so new event types
    never break the connector.
    """
    if not isinstance(body, dict):
        raise ValidationError("Response body is not a JSON object")
    events = body.get("events")
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        raise ValidationError("Response 'events' must be a list of objects")
    cursor = body.get("nextCursor")
    if not isinstance(cursor, str) or not cursor:
        raise ValidationError("Response 'nextCursor' must be a non-empty string")
    has_more = body.get("hasMore")
    if not isinstance(has_more, bool):
        raise ValidationError("Response 'hasMore' must be a boolean")
    return Page(events=events, next_cursor=cursor, has_more=has_more)


class AuditApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._url = base_url.rstrip("/") + AUDIT_PATH
        self._session = session or requests.Session()
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        self._rng = rng

    def fetch_page(
        self, *, cursor: Optional[str], start_utc: Optional[str], limit: int
    ) -> Page:
        # `from` and `cursor` are mutually exclusive: the cursor wins once one exists.
        if cursor:
            params = {"cursor": cursor, "limit": limit}
        else:
            if not start_utc:
                raise ValueError("start_utc is required when there is no cursor")
            params = {"from": start_utc, "limit": limit}

        last_error = "unknown error"
        for attempt in range(1, self._max_attempts + 1):
            retry_after: Optional[float] = None
            try:
                resp = self._session.get(
                    self._url, params=params, headers=self._headers, timeout=self._timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}"
            else:
                status = resp.status_code
                if status == 200:
                    try:
                        return parse_page(resp.json())
                    except ValueError:
                        # Truncated or non-JSON body: treat as an interrupted response.
                        last_error = "invalid JSON in response"
                elif status in RETRYABLE_STATUS:
                    last_error = f"HTTP {status}"
                    retry_after = _retry_after_seconds(resp.headers.get("Retry-After"))
                else:
                    raise NonRetryableError(_describe_client_error(status))
            if attempt < self._max_attempts:
                delay = retry_after if retry_after is not None else self._backoff(attempt)
                log.warning(
                    "Innerlogic API request failed (%s); retry %d/%d in %.1fs",
                    last_error, attempt, self._max_attempts - 1, delay,
                )
                self._sleep(delay)
        raise RetryableError(
            f"Innerlogic API still failing after {self._max_attempts} attempts ({last_error})"
        )

    def _backoff(self, attempt: int) -> float:
        # Exponential backoff with full jitter.
        ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        return self._rng() * ceiling


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    try:
        return min(max(float(value), 0.0), BACKOFF_CAP_SECONDS)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        return min(max(delta, 0.0), BACKOFF_CAP_SECONDS)
    except (TypeError, ValueError):
        return None


def _describe_client_error(status: int) -> str:
    hints = {
        400: "invalid request or cursor; check INNERLOGIC_START_UTC and the saved cursor "
             "(do not reset the checkpoint to the current time)",
        401: "token invalid, expired or revoked; create a replacement token in the "
             "Innerlogic Audit Log area and update the Key Vault secret",
        403: "access unavailable; ask your Innerlogic administrator to check the "
             "organization's Audit Log access status",
    }
    return f"Innerlogic API returned HTTP {status}: " + hints.get(status, "unexpected client error")
