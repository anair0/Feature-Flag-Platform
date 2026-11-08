"""End to end: a real API process, the real Python SDK, changes made through the API.

The API server under test runs as a *separate process* from the one making changes
(this test's in-process app), so this also proves cross-process fan-out via
Postgres LISTEN/NOTIFY.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from featureflags import FlagClient

from .conftest import ON

BACKEND = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND,
        env={**os.environ},
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            health = json.loads(urllib.request.urlopen(f"{url}/health", timeout=1).read())
            if health["change_listener"] == "up":
                break
        except OSError:
            pass
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("API server did not start")
    yield url
    proc.terminate()
    proc.wait(10)


def _wait(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return time.monotonic()
        time.sleep(0.005)
    return None


def test_flag_change_reaches_sdk_within_a_second(account, server_url):
    account.create_flag()
    server, _ = account.keys()
    user = {"id": "user-1", "country": "CA"}
    with FlagClient(server, base_url=server_url, send_events=False) as sdk:
        assert sdk.is_ready()
        assert sdk.bool("new-checkout", user, default=True) is False  # off

        started = time.monotonic()
        account.set_config("new-checkout", "production", ON)
        arrived = _wait(lambda: sdk.bool("new-checkout", user, default=False) is True)
        assert arrived is not None, "change never arrived"
        latency = arrived - started
        print(f"\nflag change propagation latency: {latency * 1000:.0f} ms")
        assert latency < 1.0

        # Kill switch
        account.set_config("new-checkout", "production", {**ON, "on": False})
        assert _wait(lambda: sdk.bool("new-checkout", user, default=True) is False)

        # Rule change
        account.set_config(
            "new-checkout",
            "production",
            {
                **ON,
                "fallthrough": {"variation": 1},
                "rules": [
                    {
                        "id": "ca",
                        "clauses": [{"attribute": "country", "op": "in", "values": ["CA"]}],
                        "serve": {"variation": 0},
                    }
                ],
            },
        )
        assert _wait(
            lambda: sdk.variation_detail("new-checkout", user, False).reason.get("rule_id") == "ca"
        )
        assert sdk.bool("new-checkout", {"id": "u2", "country": "US"}, True) is False

        # Archive -> deleted from the SDK -> caller's default
        account.post("/projects/default/flags/new-checkout/archive")
        assert _wait(
            lambda: (
                sdk.variation_detail("new-checkout", user, "d").reason.get("error_kind")
                == "FLAG_NOT_FOUND"
            )
        )


def test_other_environments_changes_are_not_delivered(account, server_url):
    account.create_flag()
    server, _ = account.keys("production")
    with FlagClient(server, base_url=server_url, send_events=False) as sdk:
        seen = []
        sdk.add_listener(seen.append)
        account.set_config("new-checkout", "development", ON)
        account.create_flag("marker")  # touches production too
        assert _wait(lambda: "marker" in seen)
        assert seen == ["marker"]
        assert sdk.bool("new-checkout", {"id": "u"}, True) is False


def test_client_stream_sends_change_pings_without_data(account, server_url):
    account.create_flag(client_side=True)
    _, client_id = account.keys()
    resp = urllib.request.urlopen(
        f"{server_url}/sdk/v1/client-stream?client_id={client_id}", timeout=5
    )
    try:
        lines = []

        def read_event():
            event = {}
            while True:
                line = resp.readline().decode().rstrip("\n")
                lines.append(line)
                if line.startswith("event:"):
                    event["event"] = line[7:]
                elif line.startswith("data:"):
                    event["data"] = json.loads(line[6:])
                elif line == "" and event:
                    return event

        first = read_event()
        assert first["event"] == "change"
        account.set_config("new-checkout", "production", ON)
        ping = read_event()
        assert ping["event"] == "change"
        assert ping["data"]["env_version"] == first["data"]["env_version"] + 1
        assert set(ping["data"]) == {"env_version"}  # no flag data to the browser
    finally:
        resp.close()


def test_stream_rejects_bad_key(server_url):
    req = urllib.request.Request(
        f"{server_url}/sdk/v1/stream", headers={"Authorization": "srv-nope"}
    )
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401
