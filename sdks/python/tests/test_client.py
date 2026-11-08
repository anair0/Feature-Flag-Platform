import socket
import time

import pytest

from featureflags import FlagClient
from featureflags import client as client_mod
from featureflags.transport import Backoff

from .fake_server import FakeServer


def bool_flag(key="f", on=True, version=1, fallthrough=0, **kw):
    return {
        "key": key,
        "version": version,
        "kind": "boolean",
        "on": on,
        "variations": [True, False],
        "off_variation": 1,
        "targets": [],
        "rules": [],
        "fallthrough": {"variation": fallthrough},
        "salt": key,
        **kw,
    }


def wait_for(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    monkeypatch.setattr(Backoff, "next", lambda self: 0.05)


@pytest.fixture
def server():
    s = FakeServer(flags={"f": bool_flag()})
    yield s
    s.stop()


def make(server, **kw):
    kw.setdefault("events_flush_interval", 60)
    return FlagClient("srv-test", base_url=server.url, **kw)


def test_initializes_from_stream_and_evaluates_locally(server):
    with make(server) as c:
        assert c.is_ready()
        assert c.bool("f", {"id": "u"}, False) is True
        requests_before = len(server.auth_headers)
        for _ in range(1000):
            c.bool("f", {"id": "u"}, False)
        assert len(server.auth_headers) == requests_before  # no network per evaluation
        assert server.auth_headers[0] == "srv-test"


def test_patch_is_applied_and_listeners_fire(server):
    changed = []
    with make(server) as c:
        c.add_listener(changed.append)
        server.patch("f", bool_flag(on=False, version=2))
        assert wait_for(lambda: c.bool("f", {"id": "u"}, True) is False)
        assert changed == ["f"]


def test_deleted_flag_returns_default(server):
    with make(server) as c:
        server.patch("f", None)
        assert wait_for(
            lambda: (
                c.variation_detail("f", {"id": "u"}, "d").reason.get("error_kind")
                == "FLAG_NOT_FOUND"
            )
        )


def test_stale_patch_is_ignored(server):
    with make(server) as c:
        server.send("patch", {"env_version": 1, "key": "f", "flag": bool_flag(on=False)})
        server.patch("g", bool_flag("g"))  # a later, valid patch proves the stale one was processed
        assert wait_for(lambda: c.bool("g", {"id": "u"}, False))
        assert c.bool("f", {"id": "u"}, False) is True


def test_version_gap_triggers_resync(server):
    with make(server) as c:
        server.flags["h"] = bool_flag("h")  # v2 "missed"
        server.patch("g", bool_flag("g"), env_version=3)
        assert wait_for(lambda: server.snapshot_requests == 1)
        assert wait_for(lambda: c.bool("h", {"id": "u"}, False))


def test_server_down_at_startup_serves_defaults_without_raising():
    started = time.monotonic()
    c = FlagClient(
        "srv-x", base_url=f"http://127.0.0.1:{free_port()}", init_timeout=0.3, send_events=False
    )
    try:
        assert time.monotonic() - started < 2
        assert not c.is_ready()
        d = c.variation_detail("f", {"id": "u"}, "fallback")
        assert d.value == "fallback" and d.reason["error_kind"] == "CLIENT_NOT_READY"
    finally:
        c.close()


def test_keeps_last_known_flags_while_server_is_down_and_reconnects():
    port = free_port()
    s = FakeServer(port=port, flags={"f": bool_flag()})
    c = FlagClient("srv-x", base_url=s.url, send_events=False)
    try:
        assert c.bool("f", {"id": "u"}, False) is True
        s.stop()
        time.sleep(0.3)
        assert c.bool("f", {"id": "u"}, False) is True  # still serving last known
        s = FakeServer(port=port, flags={"f": bool_flag(on=False, version=2)}, env_version=5)
        assert wait_for(lambda: c.bool("f", {"id": "u"}, True) is False, timeout=5)
    finally:
        c.close()
        s.stop()


def test_wrong_type_returns_default(server):
    with make(server) as c:
        d = c.variation_detail("f", {"id": "u"}, "x")
        assert d.value is True  # untyped accessor returns the value
        assert c.string("f", {"id": "u"}, "x") == "x"
        assert c.number("f", {"id": "u"}, 7) == 7


def test_invalid_user_returns_default(server):
    with make(server) as c:
        assert c.bool("f", None, False) is False
        assert c.bool("f", {"name": "no id"}, False) is False


def test_internal_exception_returns_default(server, monkeypatch):
    with make(server) as c:

        def boom(*a):
            raise RuntimeError("bug")

        monkeypatch.setattr(client_mod.evaluation, "evaluate", boom)
        d = c.variation_detail("f", {"id": "u"}, "safe")
        assert d.value == "safe" and d.reason["error_kind"] == "EXCEPTION"


def test_listener_exception_does_not_break_updates(server):
    with make(server) as c:
        c.add_listener(lambda k: 1 / 0)
        server.patch("f", bool_flag(on=False, version=2))
        server.patch("g", bool_flag("g"))
        assert wait_for(lambda: c.bool("g", {"id": "u"}, False))


def test_experiment_exposures_are_sent_and_deduped(server):
    server.flags["exp"] = {
        **bool_flag("exp"),
        "fallthrough": {
            "rollout": {"kind": "experiment", "variations": [{"variation": 0, "weight": 100000}]}
        },
    }
    with make(server) as c:
        for _ in range(5):
            c.bool("exp", {"id": "u1"}, False)
        c.bool("exp", {"id": "u2"}, False)
        c.bool("f", {"id": "u1"}, False)  # not an experiment: no exposure
        c.track({"id": "u1"}, "purchase", 20.0)
        c.flush()
        exposures = [e for e in server.events if e["kind"] == "exposure"]
        assert sorted(e["user_id"] for e in exposures) == ["u1", "u2"]
        assert [e["metric_key"] for e in server.events if e["kind"] == "custom"] == ["purchase"]


def test_event_buffer_overflow_drops_instead_of_blocking(server):
    with make(server, events_capacity=10) as c:
        started = time.monotonic()
        for i in range(1000):
            c.track({"id": f"u{i}"}, "m")
        assert time.monotonic() - started < 0.5
        assert c._events.dropped == 990


def test_polling_mode(server):
    with make(server, stream=False, poll_interval=0.05) as c:
        assert c.bool("f", {"id": "u"}, False) is True
        server.flags["f"] = bool_flag(on=False)
        assert wait_for(lambda: c.bool("f", {"id": "u"}, True) is False)


def test_offline_bootstrap():
    c = FlagClient("x", offline=True, bootstrap={"env_version": 1, "flags": {"f": bool_flag()}})
    assert c.bool("f", {"id": "u"}, False) is True
    c.close()
    c.close()  # idempotent


def test_all_flags(server):
    server.flags["g"] = bool_flag("g", on=False)
    with make(server) as c:
        assert c.all_flags({"id": "u"}) == {"f": True, "g": False}
