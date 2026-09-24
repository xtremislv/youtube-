"""
Minimal in-process, per-client-IP rate limiter.

This app has no authentication in front of most of its routes (see
PRODUCTION_ROADMAP.md's Phase 2 notes) — the only guards against abuse are
the domain-specific cooldowns on the two quota-spending actions (manual
scrape, topic search). Every other route, including plain reads like GET
/api/videos, has no protection at all against a scripted client hammering
it as fast as the network allows. This module is a generic backstop: a
simple fixed-window counter per client IP, applied to every route (see
app/deps.py's ``rate_limit_dep``).

Deliberately simple: no external dependency (no Redis, no slowapi), no
sliding-window precision — just a dict keyed by (client_ip, window_number),
each window RATE_LIMIT_WINDOW_SECONDS wide. This app is deployed as a
single Uvicorn process (see render.yaml / Dockerfile — no ``--workers``
flag), so in-process state is genuinely shared across every request the
process handles; a multi-process deployment would need a shared store
(Redis) instead, since each process would otherwise count independently.

Memory is bounded by periodically dropping windows older than the current
one — this table only ever holds recent windows for recently-seen IPs, not
an ever-growing history.
"""

from __future__ import annotations

import threading
import time

WINDOW_SECONDS = 60
# Once the tracked-window table grows past this many entries, prune anything
# from a window before the current one — keeps memory bounded without a
# background thread, at the cost of a slightly more expensive check on
# whichever request happens to cross the threshold.
_PRUNE_THRESHOLD = 5_000


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, int], int] = {}

    def check(self, key: str, limit: int) -> tuple[bool, int]:
        """Records one request for ``key`` in the current window and
        returns ``(allowed, retry_after_seconds)``. ``retry_after_seconds``
        is only meaningful when ``allowed`` is False."""
        now = time.time()
        window = int(now // WINDOW_SECONDS)
        with self._lock:
            if len(self._counts) > _PRUNE_THRESHOLD:
                self._counts = {k: v for k, v in self._counts.items() if k[1] >= window}
            count_key = (key, window)
            count = self._counts.get(count_key, 0) + 1
            self._counts[count_key] = count
        if count > limit:
            retry_after = WINDOW_SECONDS - int(now % WINDOW_SECONDS)
            return False, max(retry_after, 1)
        return True, 0


# One shared instance per process — see this module's docstring on why a
# single-process deployment makes this sufficient without a shared store.
limiter = RateLimiter()
