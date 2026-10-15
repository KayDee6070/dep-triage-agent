"""Demo rate limiting.

A public endpoint backed by a model is an open tap. M0 scope §9.3 makes these
caps a precondition for publication, not a nicety: without them anyone who
finds the link can spend the project's compute, and on a metered backend its
budget.

Two independent caps, both from ``Settings``:

* **Global daily** (``demo_daily_limit``) — the total exposure ceiling.
* **Per-client per-minute** (``demo_per_minute_limit``) — stops one caller
  consuming the day's allowance in a burst.

Deliberately in-memory and therefore **per process**. The deployed service is a
single container, so a process-local counter is the whole service. Said plainly
because it would be wrong anywhere that runs more than one replica, and a
reader should not have to infer that from the absence of a datastore.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

#: Trusted-proxy header order. Hugging Face Spaces terminates TLS ahead of the
#: container, so the socket peer is always the proxy and would collapse every
#: client into one bucket.
FORWARDED_HEADERS = ("x-forwarded-for", "x-real-ip")


@dataclass(frozen=True)
class Decision:
    """Outcome of one limit check."""

    allowed: bool
    scope: str = ""
    message: str = ""
    retry_after_s: int = 0


def client_key(headers: dict[str, str], peer: str | None) -> str:
    """Identify a caller for per-client limiting.

    Takes the **first** hop of ``x-forwarded-for``: later entries are appended
    by intermediaries and are trivially spoofable by the client. This is a
    courtesy limit on a free demo, not an authorisation boundary, and it is not
    treated as one.
    """
    for header in FORWARDED_HEADERS:
        raw = headers.get(header) or headers.get(header.title())
        if raw:
            first = raw.split(",")[0].strip()
            if first:
                return first
    return peer or "unknown"


@dataclass
class RateLimiter:
    """Global daily and per-client per-minute caps."""

    daily_limit: int
    per_minute_limit: int

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _day: int = -1
    _day_count: int = 0
    _recent: dict[str, deque[float]] = field(default_factory=dict, repr=False)

    #: Clients with no activity inside the window are dropped on each check, so
    #: the map cannot grow without bound from one-off callers.
    def _sweep(self, now: float) -> None:
        for key in [k for k, hits in self._recent.items() if not hits or now - hits[-1] > 60.0]:
            del self._recent[key]

    def check(self, key: str, now: float | None = None) -> Decision:
        """Consume one unit of allowance for ``key``, or refuse.

        A refusal consumes nothing: a client that is already over its limit
        cannot push the global counter down for everybody else.
        """
        moment = time.time() if now is None else now
        with self._lock:
            day = int(moment // 86_400)
            if day != self._day:
                self._day, self._day_count = day, 0

            if self._day_count >= self.daily_limit:
                tomorrow = (day + 1) * 86_400
                return Decision(
                    allowed=False,
                    scope="daily",
                    message=(
                        f"The demo's daily cap of {self.daily_limit} requests is spent. "
                        "The evaluation report below is unaffected."
                    ),
                    retry_after_s=max(1, int(tomorrow - moment)),
                )

            self._sweep(moment)
            hits = self._recent.setdefault(key, deque())
            while hits and moment - hits[0] >= 60.0:
                hits.popleft()

            if len(hits) >= self.per_minute_limit:
                return Decision(
                    allowed=False,
                    scope="per_minute",
                    message=(
                        f"Limit is {self.per_minute_limit} requests per minute. "
                        "The evaluation report below is unaffected."
                    ),
                    retry_after_s=max(1, int(60.0 - (moment - hits[0])) + 1),
                )

            hits.append(moment)
            self._day_count += 1
            return Decision(allowed=True)

    def snapshot(self) -> dict[str, int]:
        """Current usage, for ``/health``. Never includes client identifiers."""
        with self._lock:
            return {
                "daily_limit": self.daily_limit,
                "daily_used": self._day_count,
                "per_minute_limit": self.per_minute_limit,
                "tracked_clients": len(self._recent),
            }
