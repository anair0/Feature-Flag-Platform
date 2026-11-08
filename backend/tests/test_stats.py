import math
import random

import pytest

from app.services.stats import (
    VariationStats,
    analyze,
    chi_square_sf,
    srm_test,
    two_proportion_z_test,
    wilson_interval,
)


@pytest.mark.parametrize(
    "stat,df,p",
    [
        (3.841459, 1, 0.05),
        (6.634897, 1, 0.01),
        (5.991465, 2, 0.05),
        (7.814728, 3, 0.05),
        (0.0, 2, 1.0),
        (30.0, 1, 4.3e-8),
        (2.0, 10, 0.99634),
    ],
)
def test_chi_square_sf_matches_tables(stat, df, p):
    assert math.isclose(chi_square_sf(stat, df), p, rel_tol=1e-3, abs_tol=1e-9)


def test_wilson_interval():
    lo, hi = wilson_interval(50, 100)
    assert math.isclose(lo, 0.4038, abs_tol=1e-3) and math.isclose(hi, 0.5962, abs_tol=1e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    lo, _ = wilson_interval(0, 50)
    assert lo == 0.0


def test_z_test():
    z, p = two_proportion_z_test(100, 1000, 130, 1000)
    # pooled p = 0.115, se = sqrt(0.115 * 0.885 * 2/1000) = 0.014267, z = 0.03 / se
    assert math.isclose(z, 2.1027, abs_tol=1e-3) and math.isclose(p, 0.0355, abs_tol=1e-3)
    assert two_proportion_z_test(0, 0, 1, 10) == (0.0, 1.0)


def test_srm_detects_broken_split():
    _, p_ok = srm_test([5030, 4970], [50, 50])
    _, p_bad = srm_test([5600, 4400], [50, 50])
    assert p_ok > 0.5 and p_bad < 1e-6


def _groups(users, conv, weights=(1, 1)):
    return [
        VariationStats(i, f"v{i}", u, c, 0.0, w)
        for i, (u, c, w) in enumerate(zip(users, conv, weights, strict=True))
    ]


def test_analysis_finds_real_effect():
    a = analyze(_groups([5000, 5000], [500, 650]), 0)
    assert a.conclusive and a.comparisons[0]["significant"]
    assert math.isclose(a.comparisons[0]["relative_lift"], 0.3, abs_tol=1e-9)


def test_srm_blocks_conclusions_even_with_tiny_p():
    a = analyze(_groups([6000, 4000], [600, 800]), 0)
    assert a.srm["mismatch"] and not a.conclusive
    assert not a.comparisons[0]["significant"]
    assert any("Sample ratio mismatch" in w for w in a.warnings)


def test_too_small_sample_is_not_conclusive():
    a = analyze(_groups([40, 40], [2, 20]), 0, min_sample_per_variation=100)
    assert not a.conclusive and not a.comparisons[0]["significant"]
    assert any("peeking" in w for w in a.warnings)


def test_bonferroni_adjusts_for_multiple_treatments():
    a = analyze(_groups([1000] * 4, [100, 125, 100, 100], (1, 1, 1, 1)), 0)
    c = a.comparisons[0]
    assert math.isclose(c["p_value_adjusted"], min(1, c["p_value"] * 3))


def test_false_positive_rate_is_controlled_under_null():
    """A/A simulation: with no real effect, 'significant' should appear ~alpha of the time."""
    rng = random.Random(7)
    trials, hits = 400, 0
    for _ in range(trials):
        conv = [sum(rng.random() < 0.1 for _ in range(1000)) for _ in range(2)]
        if analyze(_groups([1000, 1000], conv), 0).comparisons[0]["significant"]:
            hits += 1
    assert hits / trials < 0.09
