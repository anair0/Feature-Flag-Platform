"""Shared spec test vectors. The TypeScript SDK runs the same files."""

import pytest

from featureflags.evaluation import bucket, evaluate

from .conftest import load_vectors

EVAL_CASES = load_vectors("evaluation.json")
BUCKET_CASES = load_vectors("bucketing.json")


@pytest.mark.parametrize("case", EVAL_CASES, ids=[c["name"] for c in EVAL_CASES])
def test_evaluation(case):
    assert evaluate(case["flag"], case["user"]).to_dict() == case["expected"]


@pytest.mark.parametrize(
    "case", BUCKET_CASES, ids=[f"{c['salt']}:{c['value']!r}" for c in BUCKET_CASES]
)
def test_bucketing(case):
    assert bucket(case["salt"], case["value"]) == case["bucket"]
