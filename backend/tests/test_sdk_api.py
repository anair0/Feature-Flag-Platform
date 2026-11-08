from .conftest import ON


def test_server_key_downloads_rules_in_spec_format(account):
    account.create_flag()
    account.set_config(
        "new-checkout",
        "production",
        {
            **ON,
            "rules": [
                {
                    "id": "ca",
                    "clauses": [{"attribute": "country", "op": "in", "values": ["CA"]}],
                    "serve": {"variation": 0},
                }
            ],
        },
    )
    server, _ = account.keys()
    snap = account.client.get("/sdk/v1/flags", headers={"Authorization": server}).json()
    flag = snap["flags"]["new-checkout"]
    assert set(flag) == {
        "key",
        "version",
        "kind",
        "on",
        "variations",
        "off_variation",
        "targets",
        "rules",
        "fallthrough",
        "salt",
        "client_side",
    }
    assert flag["on"] is True and flag["version"] == 2 and flag["salt"] == "new-checkout"
    assert snap["env_version"] >= 2


def test_env_version_increments_per_change(account):
    server, _ = account.keys()
    get = lambda: account.client.get("/sdk/v1/flags", headers={"Authorization": server}).json()  # noqa: E731
    v0 = get()["env_version"]
    account.create_flag()
    account.set_config("new-checkout", "production", ON)
    assert get()["env_version"] == v0 + 2


def test_key_types_are_enforced(account, client):
    server, client_id = account.keys()
    assert client.get("/sdk/v1/flags").status_code == 401
    assert client.get("/sdk/v1/flags", headers={"Authorization": "srv-bogus"}).status_code == 401
    # The public client-side ID must never fetch rules.
    assert client.get("/sdk/v1/flags", headers={"Authorization": client_id}).status_code == 403
    assert (
        client.post(
            "/sdk/v1/evaluate", headers={"X-Client-Id": server}, json={"user": {"id": "u"}}
        ).status_code
        == 403
    )


def test_browser_evaluate_returns_only_values_of_client_side_flags(account, client):
    account.create_flag("public-banner", client_side=True)
    account.create_flag("secret-launch")
    rules = [
        {
            "id": "vip",
            "clauses": [{"attribute": "id", "op": "in", "values": ["vip-1"]}],
            "serve": {"variation": 0},
        }
    ]
    account.set_config(
        "public-banner", "production", {**ON, "fallthrough": {"variation": 1}, "rules": rules}
    )
    _, client_id = account.keys()
    r = client.post(
        "/sdk/v1/evaluate", headers={"X-Client-Id": client_id}, json={"user": {"id": "vip-1"}}
    )
    body = r.json()
    assert set(body["flags"]) == {"public-banner"}  # unreleased flag names don't leak
    assert body["flags"]["public-banner"]["value"] is True
    assert "clauses" not in r.text and "targets" not in r.text  # targeting rules don't leak
    assert "vip-1" not in r.text  # nor the values inside them
    # query-param form (for EventSource-style clients)
    r2 = client.post(f"/sdk/v1/evaluate?client_id={client_id}", json={"user": {"id": "x"}})
    assert r2.json()["flags"]["public-banner"]["value"] is False


def test_making_flag_client_side_publishes_it(account, client):
    account.create_flag()
    _, client_id = account.keys()
    ev = lambda: client.post(
        "/sdk/v1/evaluate",
        headers={"X-Client-Id": client_id},  # noqa: E731
        json={"user": {"id": "u"}},
    ).json()["flags"]
    assert ev() == {}
    account.patch("/projects/default/flags/new-checkout", {"client_side": True})
    assert "new-checkout" in ev()


def test_key_rotation(account, client):
    old, _ = account.keys()
    auth = lambda k: client.get("/sdk/v1/flags", headers={"Authorization": k}).status_code  # noqa: E731
    new, _ = account.keys()
    assert auth(old) == 401 and auth(new) == 200
    r = account.post(
        "/projects/default/environments/production/keys/rotate",
        {"kind": "server", "grace_seconds": 3600},
    )
    newer = r.json()["value"]
    assert auth(new) == 200 and auth(newer) == 200  # grace period


def test_server_keys_are_shown_once(account):
    account.keys()
    listed = account.get("/projects/default/environments/production/keys").json()
    server = [k for k in listed if k["kind"] == "server"]
    assert server and all(k["value"] is None for k in server)
    assert all(k["value"].startswith("cli-") for k in listed if k["kind"] == "client")


def test_event_ingestion(account, client):
    server, client_id = account.keys()
    events = [
        {"kind": "exposure", "user_id": "u1", "flag_key": "f", "variation_index": 0},
        {"kind": "custom", "user_id": "u1", "metric_key": "purchase", "value": 9.5},
        {"kind": "exposure", "user_id": "u1"},  # missing fields: rejected, not an error
    ]
    r = client.post("/sdk/v1/events", headers={"Authorization": server}, json={"events": events})
    assert r.status_code == 202 and r.json() == {"accepted": 2, "rejected": 1}
    r = client.post(
        "/sdk/v1/events", headers={"X-Client-Id": client_id}, json={"events": events[:1]}
    )
    assert r.json()["accepted"] == 1
