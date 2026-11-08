import random

from featureflags.evaluation import evaluate

EXPERIMENT = {
    "on": True,
    "off_variation": 0,
    "targets": [],
    "rules": [],
    "fallthrough": {
        "rollout": {
            "kind": "experiment",
            "variations": [{"variation": 0, "weight": 50000}, {"variation": 1, "weight": 50000}],
        }
    },
}
RATES = {0: 0.10, 1: 0.16}


def _simulate(account, server_key, n_users=3000, skew_to=None):
    flag = account.client.get("/sdk/v1/flags", headers={"Authorization": server_key}).json()[
        "flags"
    ]["checkout"]
    rng = random.Random(1)
    events = []
    for i in range(n_users):
        user = {"id": f"user-{i}"}
        v = evaluate(flag, user).variation_index
        if skew_to is not None and v != skew_to and rng.random() < 0.3:
            continue  # simulate broken assignment: some users of one arm never get logged
        events.append(
            {
                "kind": "exposure",
                "user_id": user["id"],
                "flag_key": "checkout",
                "variation_index": v,
                "timestamp": 1_700_000_000_000,
            }
        )
        if rng.random() < RATES[v]:
            events.append(
                {
                    "kind": "custom",
                    "user_id": user["id"],
                    "metric_key": "purchase",
                    "value": 20.0,
                    "timestamp": 1_700_000_001_000,
                }
            )
    # a purchase *before* exposure must not count
    events.append(
        {
            "kind": "custom",
            "user_id": "user-0",
            "metric_key": "purchase",
            "timestamp": 1_600_000_000_000,
        }
    )
    for i in range(0, len(events), 1000):
        r = account.client.post(
            "/sdk/v1/events",
            headers={"Authorization": server_key},
            json={"events": events[i : i + 1000]},
        )
        assert r.status_code == 202


def _setup(account):
    account.create_flag("checkout", kind="string", variations=["control", "one-page"])
    assert account.set_config("checkout", "production", EXPERIMENT).status_code == 200
    server, _ = account.keys()
    return server


def test_experiment_results(account):
    server = _setup(account)
    _simulate(account, server)
    r = account.get(
        "/projects/default/flags/checkout/environments/production/experiment",
        params={"metric": "purchase"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    users = [v["users"] for v in body["variations"]]
    assert sum(users) == 3000 and abs(users[0] - users[1]) < 200
    assert not body["srm"]["mismatch"]
    rates = [v["conversion_rate"] for v in body["variations"]]
    assert 0.08 < rates[0] < 0.12 and 0.13 < rates[1] < 0.19
    assert body["comparisons"][0]["significant"] and body["conclusive"]


def test_broken_assignment_is_flagged(account):
    server = _setup(account)
    _simulate(account, server, skew_to=1)
    body = account.get(
        "/projects/default/flags/checkout/environments/production/experiment",
        params={"metric": "purchase"},
    ).json()
    assert body["srm"]["mismatch"] and not body["conclusive"]
    assert not body["comparisons"][0]["significant"]


def test_users_in_two_variations_are_excluded(account):
    server = _setup(account)
    ev = [
        {"kind": "exposure", "user_id": "flip", "flag_key": "checkout", "variation_index": i}
        for i in (0, 1)
    ]
    account.client.post("/sdk/v1/events", headers={"Authorization": server}, json={"events": ev})
    body = account.get(
        "/projects/default/flags/checkout/environments/production/experiment",
        params={"metric": "purchase"},
    ).json()
    assert sum(v["users"] for v in body["variations"]) == 0
    assert any("more than one variation" in w for w in body["warnings"])


def test_no_experiment_configured(account):
    account.create_flag()
    r = account.get(
        "/projects/default/flags/new-checkout/environments/production/experiment",
        params={"metric": "purchase"},
    )
    assert r.status_code == 409
