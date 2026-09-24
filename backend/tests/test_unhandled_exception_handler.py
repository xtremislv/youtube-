"""
The global exception handler (app/main.py's unhandled_exception_handler) —
the backstop for any exception a route doesn't already turn into a clean
HTTPException. Confirms it returns a safe, generic JSON body (not a bare
"Internal Server Error" plain-text response, and never the real exception
message, which might embed something not meant for a client) rather than
letting Starlette's own default handler take over.

Uses its own TestClient with raise_server_exceptions=False rather than the
shared `client` fixture: Starlette's TestClient re-raises an unhandled
exception into the *test* by default (useful so a real bug elsewhere in the
suite fails loudly instead of being silently swallowed), which is exactly
the behavior this test needs to disable to observe what a real deployment
(uvicorn, which never re-raises to a caller) actually sends over the wire.
"""

from fastapi.testclient import TestClient

from app.database import get_db
from app.deps import settings_dep
from app.main import app


def _boom_db():
    raise RuntimeError("simulated unexpected failure with a secret-looking key=abc123 in it")
    yield  # pragma: no cover - unreachable, keeps this a generator like get_db


def test_unhandled_exception_returns_safe_generic_500(test_settings):
    app.dependency_overrides[get_db] = _boom_db
    app.dependency_overrides[settings_dep] = lambda: test_settings
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/system/status")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "Something went wrong on the server. Please try again."}
    # The real exception's text (and anything secret-shaped it might carry)
    # must never reach the response body.
    assert "secret" not in resp.text
    assert "key=abc123" not in resp.text
