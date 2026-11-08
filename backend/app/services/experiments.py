"""Turn raw exposure/metric events into per-variation stats."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Environment, Flag, FlagConfig
from app.services.stats import Analysis, VariationStats, analyze

# A user counts once, in the variation they were first exposed to; users exposed to more
# than one variation are excluded and reported. A conversion counts only if the metric
# event happened at or after the user's first exposure.
RESULTS_SQL = text("""
WITH exposed AS MATERIALIZED (
    SELECT user_id, min(variation_index) AS v, max(variation_index) AS v_max, min(ts) AS first_ts
    FROM events
    WHERE environment_id = :env AND kind = 'exposure' AND flag_key = :flag
    GROUP BY user_id
),
metric AS MATERIALIZED (
    SELECT user_id, ts, coalesce(value, 0) AS value
    FROM events
    WHERE environment_id = :env AND kind = 'custom' AND metric_key = :metric
),
converted AS (
    SELECT e.user_id, sum(m.value) AS total
    FROM exposed e JOIN metric m ON m.user_id = e.user_id AND m.ts >= e.first_ts
    WHERE e.v = e.v_max
    GROUP BY e.user_id
)
SELECT e.v AS variation_index, count(*) AS users, count(c.user_id) AS conversions,
       coalesce(sum(c.total), 0) AS value_sum
FROM exposed e LEFT JOIN converted c USING (user_id)
WHERE e.v = e.v_max
GROUP BY e.v
""")

MIXED_SQL = text("""
SELECT count(*) FROM (
    SELECT user_id FROM events
    WHERE environment_id = :env AND kind = 'exposure' AND flag_key = :flag
    GROUP BY user_id HAVING min(variation_index) <> max(variation_index)
) x
""")


def experiment_weights(cfg: FlagConfig, n_variations: int) -> list[float] | None:
    """Configured split of the first experiment rollout (fallthrough, then rules)."""
    serves = [cfg.fallthrough] + [r.get("serve", {}) for r in cfg.rules]
    for serve in serves:
        rollout = (serve or {}).get("rollout")
        if rollout and rollout.get("kind") == "experiment":
            weights = [0.0] * n_variations
            for wv in rollout["variations"]:
                if 0 <= wv["variation"] < n_variations:
                    weights[wv["variation"]] = float(wv["weight"])
            return weights
    return None


def results(
    db: Session,
    flag: Flag,
    env: Environment,
    cfg: FlagConfig,
    metric: str,
    control: int,
    alpha: float,
    min_sample: int,
) -> tuple[Analysis | None, str | None]:
    weights = experiment_weights(cfg, len(flag.variations))
    if weights is None:
        return None, "This flag has no experiment rollout in this environment."
    params = {"env": env.id, "flag": flag.key, "metric": metric}
    rows = {r.variation_index: r for r in db.execute(RESULTS_SQL, params)}
    mixed = db.execute(MIXED_SQL, params).scalar_one()
    groups = [
        VariationStats(
            variation_index=i,
            value=flag.variations[i],
            users=rows[i].users if i in rows else 0,
            conversions=rows[i].conversions if i in rows else 0,
            value_sum=float(rows[i].value_sum) if i in rows else 0.0,
            weight=w,
        )
        for i, w in enumerate(weights)
        if w > 0
    ]
    return analyze(
        groups,
        control,
        alpha=alpha,
        min_sample_per_variation=min_sample,
        mixed_assignment_users=mixed,
    ), None
