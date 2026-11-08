from app.core.config import settings
from app.core.ratelimit import TokenBuckets


def test_token_bucket_refills():
    b = TokenBuckets(rate=1.0, burst=2)
    assert b.allow("k", now=0) and b.allow("k", now=0)
    assert not b.allow("k", now=0)
    assert b.allow("k", now=1.0)
    assert b.allow("other", now=0)  # independent keys


def test_auth_endpoints_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    codes = [
        client.post("/api/auth/login", json={"email": "x@y.co", "password": "p"}).status_code
        for _ in range(settings.auth_burst + 3)
    ]
    assert codes[0] == 401 and codes[-1] == 429
