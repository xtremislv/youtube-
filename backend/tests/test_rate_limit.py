"""
The blanket per-IP rate limit (app/rate_limit.py, wired in as
app/deps.py's rate_limit_dep — see app/main.py). Disabled by default for
every other test (tests/conftest.py's test_settings), since a shared
in-process counter would otherwise see the whole suite's request volume as
one client; exercised directly here instead.
"""

from app.rate_limit import RateLimiter


def test_requests_within_limit_are_allowed():
    limiter = RateLimiter()
    for _ in range(5):
        allowed, _ = limiter.check("1.2.3.4", limit=5)
        assert allowed


def test_request_past_limit_is_blocked_with_retry_after():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check("1.2.3.4", limit=5)
    allowed, retry_after = limiter.check("1.2.3.4", limit=5)
    assert not allowed
    assert retry_after > 0


def test_limit_is_tracked_independently_per_key():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check("1.2.3.4", limit=5)
    # A different client (different IP) should be unaffected by the first
    # one having exhausted its own limit.
    allowed, _ = limiter.check("5.6.7.8", limit=5)
    assert allowed


def test_endpoint_returns_429_with_retry_after_once_rate_limited(client, test_settings):
    test_settings.rate_limit_enabled = True
    test_settings.rate_limit_requests_per_minute = 3
    # app.rate_limit.limiter is one process-wide counter, so a fixed,
    # test-specific X-Forwarded-For keeps this test's requests in their own
    # bucket regardless of what other tests (or a re-run within the same
    # 60s window) have already recorded for TestClient's own fixed IP.
    headers = {"X-Forwarded-For": "203.0.113.10"}

    for _ in range(3):
        resp = client.get("/api/system/status", headers=headers)
        assert resp.status_code == 200

    blocked = client.get("/api/system/status", headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_healthz_is_exempt_from_rate_limiting(client, test_settings):
    test_settings.rate_limit_enabled = True
    test_settings.rate_limit_requests_per_minute = 1
    headers = {"X-Forwarded-For": "203.0.113.11"}

    # Exhaust the (tiny) limit on a normal route first.
    client.get("/api/system/status", headers=headers)
    assert client.get("/api/system/status", headers=headers).status_code == 429

    # /healthz should still succeed regardless — uptime monitors/Render's
    # own health check poll this on their own schedule and shouldn't be
    # able to trip (or be tripped by) the same budget as real API traffic.
    assert client.get("/healthz", headers=headers).status_code == 200
