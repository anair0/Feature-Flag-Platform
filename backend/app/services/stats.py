"""Experiment statistics: pure functions, standard library only.

The traps this module guards against (see docs/design-decisions.md#experiments):
- Broken assignment: a sample-ratio-mismatch (SRM) test. If group sizes don't match
  the configured split, randomization is broken and no comparison can be trusted.
- Peeking: results are marked "not yet conclusive" until each group reaches a
  sample size fixed in advance. Stopping when p first dips below alpha inflates
  false positives far beyond alpha.
- Many comparisons: p-values are Bonferroni-adjusted across the treatment-vs-control
  comparisons, so "something is significant" stays at the stated error rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SRM_ALPHA = 0.001


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Inverse normal CDF by bisection (plenty precise for confidence intervals)."""
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = normal_ppf(1 - (1 - confidence) / 2)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def two_proportion_z_test(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """Two-sided test of p1 == p2. Returns (z, p_value)."""
    if n1 == 0 or n2 == 0:
        return (0.0, 1.0)
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return (0.0, 1.0)
    z = (x2 / n2 - x1 / n1) / se
    return (z, 2 * (1 - normal_cdf(abs(z))))


def _gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes 6.2)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:  # series for P, then Q = 1 - P
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-15:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    b = x + 1 - a  # continued fraction for Q
    c, d = 1 / 1e-300, 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi_square_sf(stat: float, df: int) -> float:
    return _gamma_q(df / 2, stat / 2)


def srm_test(observed: list[int], expected_weights: list[float]) -> tuple[float, float]:
    """Chi-square goodness of fit of group sizes vs the configured split. (stat, p)."""
    total = sum(observed)
    wsum = sum(expected_weights)
    if total == 0 or wsum == 0 or len(observed) < 2:
        return (0.0, 1.0)
    stat = 0.0
    for o, w in zip(observed, expected_weights, strict=True):
        e = total * w / wsum
        if e > 0:
            stat += (o - e) ** 2 / e
    return (stat, chi_square_sf(stat, len(observed) - 1))


@dataclass
class VariationStats:
    variation_index: int
    value: object
    users: int
    conversions: int
    value_sum: float
    weight: float

    @property
    def rate(self) -> float:
        return self.conversions / self.users if self.users else 0.0


@dataclass
class Analysis:
    variations: list[dict]
    srm: dict
    comparisons: list[dict]
    warnings: list[str] = field(default_factory=list)
    conclusive: bool = False


def analyze(
    groups: list[VariationStats],
    control_index: int,
    *,
    alpha: float = 0.05,
    min_sample_per_variation: int = 100,
    mixed_assignment_users: int = 0,
) -> Analysis:
    warnings: list[str] = []
    srm_stat, srm_p = srm_test([g.users for g in groups], [g.weight for g in groups])
    srm_detected = srm_p < SRM_ALPHA
    if srm_detected:
        warnings.append(
            f"Sample ratio mismatch (p={srm_p:.2g}): group sizes don't match the configured "
            "split, so assignment is broken. Do not trust these results; find the cause first."
        )
    if mixed_assignment_users:
        warnings.append(
            f"{mixed_assignment_users} user(s) were exposed to more than one variation and are "
            "excluded. A large number suggests the flag config changed mid-experiment."
        )
    under = [g for g in groups if g.users < min_sample_per_variation]
    if under:
        warnings.append(
            f"Not every variation has reached the planned {min_sample_per_variation} users. "
            "Don't stop the experiment on an early result: peeking inflates false positives."
        )

    control = next((g for g in groups if g.variation_index == control_index), None)
    treatments = [g for g in groups if g.variation_index != control_index]
    m = max(len(treatments), 1)
    comparisons = []
    if control is not None:
        for t in treatments:
            z, p = two_proportion_z_test(control.conversions, control.users, t.conversions, t.users)
            p_adj = min(1.0, p * m)
            lift = (t.rate - control.rate) / control.rate if control.rate else None
            comparisons.append(
                {
                    "variation_index": t.variation_index,
                    "vs_control": control_index,
                    "absolute_difference": t.rate - control.rate,
                    "relative_lift": lift,
                    "z": z,
                    "p_value": p,
                    "p_value_adjusted": p_adj,
                    "significant": p_adj < alpha and not srm_detected and not under,
                }
            )

    variations = []
    for g in groups:
        lo, hi = wilson_interval(g.conversions, g.users, 1 - alpha)
        variations.append(
            {
                "variation_index": g.variation_index,
                "value": g.value,
                "users": g.users,
                "conversions": g.conversions,
                "conversion_rate": g.rate,
                "conversion_rate_ci": [lo, hi],
                "mean_value_per_user": g.value_sum / g.users if g.users else 0.0,
                "expected_share": g.weight / (sum(x.weight for x in groups) or 1),
            }
        )
    return Analysis(
        variations=variations,
        srm={"chi_square": srm_stat, "p_value": srm_p, "mismatch": srm_detected},
        comparisons=comparisons,
        warnings=warnings,
        conclusive=not srm_detected and not under and control is not None,
    )
