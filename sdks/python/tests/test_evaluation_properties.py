"""Properties the spec promises about rollouts, checked over many users."""

from featureflags.evaluation import bucket, evaluate

USERS = [f"user-{i}" for i in range(5000)]


def _flag(pct_on: int) -> dict:
    weight = pct_on * 1000
    return {
        "key": "f",
        "on": True,
        "variations": [True, False],
        "off_variation": 1,
        "fallthrough": {
            "rollout": {
                "variations": [
                    {"variation": 0, "weight": weight},
                    {"variation": 1, "weight": 100_000 - weight},
                ]
            }
        },
    }


def _on_set(pct: int) -> set:
    flag = _flag(pct)
    return {u for u in USERS if evaluate(flag, {"id": u}).value is True}


def test_raising_rollout_only_adds_users():
    previous: set = set()
    for pct in (0, 1, 5, 10, 20, 50, 90, 100):
        current = _on_set(pct)
        assert previous <= current, f"users were removed when raising to {pct}%"
        previous = current


def test_rollout_is_sticky():
    assert _on_set(30) == _on_set(30)


def test_rollout_fraction_is_close_to_target():
    assert abs(len(_on_set(10)) / len(USERS) - 0.10) < 0.02


def test_buckets_are_independent_across_salts():
    a = {u for u in USERS if bucket("flag-a", u) < 10_000}
    b = {u for u in USERS if bucket("flag-b", u) < 10_000}
    overlap = len(a & b) / max(len(a), 1)
    assert overlap < 0.2  # independent: ~10% expected, identical salts would give 100%


def test_buckets_in_range():
    assert all(0 <= bucket("s", u) < 100_000 for u in USERS)
