"""Pure flag evaluation. Implements spec/evaluation.md exactly.

No I/O, no globals, no exceptions escaping: given a flag config (dict) and a
user (dict), return an EvaluationResult. The backend reuses this module for
browser (remote) evaluation so server and SDK answers can't drift.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

BUCKET_SCALE = 100_000
MAX_SAFE_INT = 2**53 - 1


@dataclass(frozen=True)
class EvaluationResult:
    value: Any
    variation_index: Optional[int]
    reason: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"value": self.value, "variation_index": self.variation_index, "reason": self.reason}


class _Malformed(Exception):
    pass


def _error(kind: str) -> EvaluationResult:
    return EvaluationResult(None, None, {"kind": "ERROR", "error_kind": kind})


# ---------------------------------------------------------------- type helpers


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _same_scalar(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


# ---------------------------------------------------------------------- semver

_SEMVER = re.compile(
    r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$"
)


def parse_semver(s: Any) -> Optional[tuple]:
    if not isinstance(s, str):
        return None
    m = _SEMVER.match(s)
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor or 0), int(patch or 0), pre.split(".") if pre else [])


def _cmp_prerelease(a: list, b: list) -> int:
    if not a and not b:
        return 0
    if not a:
        return 1  # release > prerelease
    if not b:
        return -1
    for x, y in zip(a, b):
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            c = (int(x) > int(y)) - (int(x) < int(y))
        elif xn:
            c = -1
        elif yn:
            c = 1
        else:
            c = (x > y) - (x < y)
        if c:
            return c
    return (len(a) > len(b)) - (len(a) < len(b))


def compare_semver(a: tuple, b: tuple) -> int:
    for x, y in zip(a[:3], b[:3]):
        if x != y:
            return 1 if x > y else -1
    return _cmp_prerelease(a[3], b[3])


def _semver_op(pred: Callable[[int], bool]) -> Callable[[Any, Any], bool]:
    def op(u: Any, v: Any) -> bool:
        pu, pv = parse_semver(u), parse_semver(v)
        return pu is not None and pv is not None and pred(compare_semver(pu, pv))

    return op


def _str_op(fn: Callable[[str, str], bool]) -> Callable[[Any, Any], bool]:
    return lambda u, v: isinstance(u, str) and isinstance(v, str) and fn(u, v)


def _num_op(fn: Callable[[float, float], bool]) -> Callable[[Any, Any], bool]:
    return lambda u, v: _is_number(u) and _is_number(v) and fn(u, v)


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "in": _same_scalar,
    "starts_with": _str_op(lambda u, v: u.startswith(v)),
    "ends_with": _str_op(lambda u, v: u.endswith(v)),
    "contains": _str_op(lambda u, v: v in u),
    "lt": _num_op(lambda u, v: u < v),
    "lte": _num_op(lambda u, v: u <= v),
    "gt": _num_op(lambda u, v: u > v),
    "gte": _num_op(lambda u, v: u >= v),
    "semver_eq": _semver_op(lambda c: c == 0),
    "semver_lt": _semver_op(lambda c: c < 0),
    "semver_gt": _semver_op(lambda c: c > 0),
}


# ------------------------------------------------------------------- matching


def clause_matches(clause: dict, user: dict) -> bool:
    op = OPERATORS.get(clause.get("op"))
    if op is None:
        return False
    u = user.get(clause.get("attribute"))
    if u is None:
        return False
    values = clause.get("values") or []
    candidates = [x for x in u if x is not None] if isinstance(u, list) else [u]
    matched = any(op(c, v) for c in candidates for v in values)
    return not matched if clause.get("negate") else matched


def rule_matches(rule: dict, user: dict) -> bool:
    clauses = rule.get("clauses") or []
    return bool(clauses) and all(clause_matches(c, user) for c in clauses)


# ------------------------------------------------------------------ bucketing


def _bucket_string(raw: Any) -> Optional[str]:
    if isinstance(raw, str):
        return raw
    if _is_number(raw):
        if isinstance(raw, float):
            if not raw.is_integer():
                return None
            raw = int(raw)
        if abs(raw) <= MAX_SAFE_INT:
            return str(raw)
    return None


def bucket(salt: str, value: Any) -> int:
    """Return the user's bucket in [0, 100000)."""
    s = _bucket_string(value)
    if s is None:
        return 0
    digest = hashlib.sha1(f"{salt}.{s}".encode()).hexdigest()
    return int(digest[:8], 16) % BUCKET_SCALE


# ------------------------------------------------------------------ evaluation


def _variation(flag: dict, index: Any) -> tuple[Any, int]:
    variations = flag.get("variations")
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not isinstance(variations, list)
        or not 0 <= index < len(variations)
    ):
        raise _Malformed()
    return variations[index], index


def _serve(flag: dict, serve: Any, user: dict) -> tuple[Any, int, bool]:
    if not isinstance(serve, dict):
        raise _Malformed()
    if "variation" in serve:
        value, idx = _variation(flag, serve["variation"])
        return value, idx, False
    rollout = serve.get("rollout")
    if not isinstance(rollout, dict) or not rollout.get("variations"):
        raise _Malformed()
    salt = flag.get("salt") or flag.get("key") or ""
    b = bucket(salt, user.get(rollout.get("bucket_by") or "id"))
    weighted = rollout["variations"]
    chosen = weighted[-1]
    total = 0
    for wv in weighted:
        total += wv.get("weight", 0)
        if b < total:
            chosen = wv
            break
    value, idx = _variation(flag, chosen.get("variation"))
    return value, idx, rollout.get("kind") == "experiment"


def evaluate(flag: dict, user: Any) -> EvaluationResult:
    try:
        if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user["id"]:
            return _error("USER_NOT_SPECIFIED")
        if not isinstance(flag, dict):
            return _error("MALFORMED_FLAG")

        if flag.get("on") is not True:
            off = flag.get("off_variation")
            if off is None:
                return EvaluationResult(None, None, {"kind": "OFF"})
            value, idx = _variation(flag, off)
            return EvaluationResult(value, idx, {"kind": "OFF"})

        for target in flag.get("targets") or []:
            if user["id"] in (target.get("values") or []):
                value, idx = _variation(flag, target.get("variation"))
                return EvaluationResult(value, idx, {"kind": "TARGET_MATCH"})

        for i, rule in enumerate(flag.get("rules") or []):
            if rule_matches(rule, user):
                value, idx, exp = _serve(flag, rule.get("serve"), user)
                reason = {"kind": "RULE_MATCH", "rule_index": i, "rule_id": rule.get("id")}
                if exp:
                    reason["in_experiment"] = True
                return EvaluationResult(value, idx, reason)

        value, idx, exp = _serve(flag, flag.get("fallthrough"), user)
        reason = {"kind": "FALLTHROUGH"}
        if exp:
            reason["in_experiment"] = True
        return EvaluationResult(value, idx, reason)
    except Exception:  # malformed config of any shape: never raise
        return _error("MALFORMED_FLAG")
