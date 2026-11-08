"""Writes spec/test-vectors/*.json (run: python spec/test-vectors/generate.py spec/test-vectors).

Expected values are hand-specified, NOT computed by any engine, so they test every engine.
"""
import copy, json, sys
from pathlib import Path

out = Path(sys.argv[1])
BASE = {"key": "new-checkout", "version": 1, "kind": "boolean", "on": True, "variations": [True, False],
        "off_variation": 1, "targets": [], "rules": [], "fallthrough": {"variation": 1},
        "salt": "new-checkout", "client_side": False}

def flag(**kw):
    f = copy.deepcopy(BASE); f.update(kw); return f

def clause(attr, op, values, negate=False):
    return {"attribute": attr, "op": op, "values": values, "negate": negate}

def rule(rid, clauses, serve=None):
    return {"id": rid, "clauses": clauses, "serve": serve or {"variation": 0}}

def res(value, idx, kind, **extra):
    return {"value": value, "variation_index": idx, "reason": {"kind": kind, **extra}}

def err(kind):
    return {"value": None, "variation_index": None, "reason": {"kind": "ERROR", "error_kind": kind}}

T = res(True, 0, "RULE_MATCH", rule_index=0, rule_id="r")
F = res(False, 1, "FALLTHROUGH")
def op_case(name, attr, op, values, user_val, match, negate=False):
    u = {"id": "u"}
    if user_val is not ...:
        u[attr] = user_val
    return {"name": name, "flag": flag(rules=[rule("r", [clause(attr, op, values, negate)])]),
            "user": u, "expected": T if match else F}

CANADA = rule("canada", [clause("country", "in", ["CA"])])
cases = [
    {"name": "off serves off_variation", "flag": flag(on=False), "user": {"id": "u"}, "expected": res(False, 1, "OFF")},
    {"name": "off with null off_variation serves null", "flag": flag(on=False, off_variation=None), "user": {"id": "u"}, "expected": res(None, None, "OFF")},
    {"name": "missing on field is off", "flag": {k: v for k, v in flag().items() if k != "on"}, "user": {"id": "u"}, "expected": res(False, 1, "OFF")},
    {"name": "on with fixed fallthrough", "flag": flag(fallthrough={"variation": 0}), "user": {"id": "u"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "user without id", "flag": flag(), "user": {"country": "CA"}, "expected": err("USER_NOT_SPECIFIED")},
    {"name": "user with empty id", "flag": flag(), "user": {"id": ""}, "expected": err("USER_NOT_SPECIFIED")},
    {"name": "user with numeric id", "flag": flag(), "user": {"id": 5}, "expected": err("USER_NOT_SPECIFIED")},
    {"name": "user is not an object", "flag": flag(), "user": "user-1", "expected": err("USER_NOT_SPECIFIED")},
    {"name": "user is null", "flag": flag(), "user": None, "expected": err("USER_NOT_SPECIFIED")},
    {"name": "invalid user beats off", "flag": flag(on=False), "user": {}, "expected": err("USER_NOT_SPECIFIED")},
    {"name": "individual target", "flag": flag(targets=[{"variation": 0, "values": ["user-1"]}]), "user": {"id": "user-1"}, "expected": res(True, 0, "TARGET_MATCH")},
    {"name": "target beats rule", "flag": flag(targets=[{"variation": 1, "values": ["user-1"]}], rules=[CANADA]), "user": {"id": "user-1", "country": "CA"}, "expected": res(False, 1, "TARGET_MATCH")},
    {"name": "first target wins", "flag": flag(targets=[{"variation": 1, "values": ["user-1"]}, {"variation": 0, "values": ["user-1"]}]), "user": {"id": "user-1"}, "expected": res(False, 1, "TARGET_MATCH")},
    {"name": "off beats target", "flag": flag(on=False, targets=[{"variation": 0, "values": ["user-1"]}]), "user": {"id": "user-1"}, "expected": res(False, 1, "OFF")},
    {"name": "rule matches", "flag": flag(rules=[CANADA]), "user": {"id": "u", "country": "CA"}, "expected": res(True, 0, "RULE_MATCH", rule_index=0, rule_id="canada")},
    {"name": "rule does not match", "flag": flag(rules=[CANADA]), "user": {"id": "u", "country": "US"}, "expected": F},
    {"name": "first matching rule wins", "flag": flag(rules=[rule("a", [clause("country", "in", ["CA"])], {"variation": 1}), rule("b", [clause("country", "in", ["CA"])], {"variation": 0})]), "user": {"id": "u", "country": "CA"}, "expected": res(False, 1, "RULE_MATCH", rule_index=0, rule_id="a")},
    {"name": "second rule matches", "flag": flag(rules=[rule("a", [clause("country", "in", ["US"])]), rule("b", [clause("country", "in", ["CA"])])]), "user": {"id": "u", "country": "CA"}, "expected": res(True, 0, "RULE_MATCH", rule_index=1, rule_id="b")},
    {"name": "rule with zero clauses never matches", "flag": flag(rules=[rule("empty", [])]), "user": {"id": "u"}, "expected": F},
    {"name": "all clauses must match", "flag": flag(rules=[rule("r", [clause("country", "in", ["CA"]), clause("plan", "in", ["pro"])])]), "user": {"id": "u", "country": "CA", "plan": "free"}, "expected": F},
    {"name": "all clauses match", "flag": flag(rules=[rule("r", [clause("country", "in", ["CA"]), clause("plan", "in", ["pro"])])]), "user": {"id": "u", "country": "CA", "plan": "pro"}, "expected": T},
    {"name": "clause values are ORed", "flag": flag(rules=[rule("r", [clause("country", "in", ["US", "CA", "MX"])])]), "user": {"id": "u", "country": "MX"}, "expected": T},
    {"name": "clause can reference id", "flag": flag(rules=[rule("r", [clause("id", "ends_with", ["@acme.com"])])]), "user": {"id": "jo@acme.com"}, "expected": T},
    op_case("missing attribute does not match", "country", "in", ["CA"], ..., False),
    op_case("missing attribute does not match even when negated", "country", "in", ["CA"], ..., False, negate=True),
    op_case("null attribute does not match even when negated", "country", "in", ["CA"], None, False, negate=True),
    op_case("negated clause matches other value", "country", "in", ["CA"], "US", True, negate=True),
    op_case("negated clause rejects listed value", "country", "in", ["CA"], "CA", False, negate=True),
    op_case("array attribute matches any element", "groups", "in", ["staff"], ["beta", "staff"], True),
    op_case("array attribute with no matching element", "groups", "in", ["staff"], ["beta"], False),
    op_case("array attribute ignores null elements", "groups", "in", ["beta"], [None, "beta"], True),
    op_case("empty array attribute negated matches", "groups", "in", ["staff"], [], True, negate=True),
    op_case("in is case sensitive", "country", "in", ["CA"], "ca", False),
    op_case("in does not coerce number to string", "level", "in", ["1"], 1, False),
    op_case("in does not coerce string to number", "level", "in", [1], "1", False),
    op_case("in treats booleans as distinct from numbers", "beta", "in", [1], True, False),
    op_case("in matches booleans", "beta", "in", [True], True, True),
    op_case("in compares numbers numerically", "level", "in", [3], 3.0, True),
    op_case("in never matches objects", "meta", "in", ["x"], {"a": "x"}, False),
    op_case("starts_with", "email", "starts_with", ["admin@"], "admin@acme.com", True),
    op_case("starts_with requires strings", "code", "starts_with", ["1"], 123, False),
    op_case("ends_with", "email", "ends_with", ["@acme.com"], "jo@acme.com", True),
    op_case("ends_with mismatch", "email", "ends_with", ["@acme.com"], "jo@acme.co", False),
    op_case("contains", "email", "contains", ["acme"], "jo@acme.com", True),
    op_case("contains is case sensitive", "email", "contains", ["ACME"], "jo@acme.com", False),
    op_case("gte number", "age", "gte", [18], 18, True),
    op_case("gt number", "age", "gt", [18], 18, False),
    op_case("lt float", "score", "lt", [0.5], 0.25, True),
    op_case("lte number", "age", "lte", [18], 19, False),
    op_case("numeric op rejects numeric string", "age", "gt", [18], "30", False),
    op_case("numeric op rejects boolean", "age", "gt", [0], True, False),
    op_case("semver_gt", "app_version", "semver_gt", ["2.4.0"], "2.4.1", True),
    op_case("semver_gt equal is false", "app_version", "semver_gt", ["2.4.0"], "2.4.0", False),
    op_case("semver_lt numeric not lexical", "app_version", "semver_lt", ["2.10.0"], "2.9.0", True),
    op_case("semver prerelease below release", "app_version", "semver_lt", ["2.4.0"], "2.4.0-beta.1", True),
    op_case("semver missing parts are zero", "app_version", "semver_eq", ["2.4.0"], "2.4", True),
    op_case("semver build metadata ignored", "app_version", "semver_eq", ["1.0.0"], "1.0.0+build.5", True),
    op_case("semver shorter prerelease set is lower", "app_version", "semver_lt", ["1.0.0-alpha.1"], "1.0.0-alpha", True),
    op_case("semver numeric identifier below alphanumeric", "app_version", "semver_lt", ["1.0.0-alpha.beta"], "1.0.0-alpha.1", True),
    op_case("semver numeric identifiers compare numerically", "app_version", "semver_lt", ["1.0.0-beta.11"], "1.0.0-beta.2", True),
    op_case("semver leading v does not parse", "app_version", "semver_eq", ["2.4.0"], "v2.4.0", False),
    op_case("semver garbage does not parse", "app_version", "semver_gt", ["1.0.0"], "latest", False),
    op_case("semver requires string", "app_version", "semver_eq", ["2.0.0"], 2, False),
    op_case("prototype property name is not an attribute", "constructor", "in", ["x"], ..., False),
    op_case("prototype property name is not an attribute when negated", "constructor", "in", ["x"], ..., False, negate=True),
    op_case("__proto__ is not an attribute when negated", "__proto__", "in", ["x"], ..., False, negate=True),
    op_case("unknown operator never matches", "country", "regex_match", ["C."], "CA", False),
    op_case("unknown operator negated still never matches", "country", "regex_match", ["C."], "CA", False, negate=True),
    {"name": "malformed fallthrough index", "flag": flag(fallthrough={"variation": 5}), "user": {"id": "u"}, "expected": err("MALFORMED_FLAG")},
    {"name": "malformed off_variation", "flag": flag(on=False, off_variation=9), "user": {"id": "u"}, "expected": err("MALFORMED_FLAG")},
    {"name": "malformed boolean index", "flag": flag(fallthrough={"variation": True}), "user": {"id": "u"}, "expected": err("MALFORMED_FLAG")},
    {"name": "malformed missing fallthrough", "flag": {k: v for k, v in flag().items() if k != "fallthrough"}, "user": {"id": "u"}, "expected": err("MALFORMED_FLAG")},
    {"name": "malformed empty rollout", "flag": flag(fallthrough={"rollout": {"kind": "rollout", "variations": []}}), "user": {"id": "u"}, "expected": err("MALFORMED_FLAG")},
    {"name": "malformed target index", "flag": flag(targets=[{"variation": 7, "values": ["u"]}]), "user": {"id": "u"}, "expected": err("MALFORMED_FLAG")},
    {"name": "malformed rule serve", "flag": flag(rules=[rule("r", [clause("country", "in", ["CA"])], {"variation": -1})]), "user": {"id": "u", "country": "CA"}, "expected": err("MALFORMED_FLAG")},
]

R10 = {"rollout": {"kind": "rollout", "variations": [{"variation": 0, "weight": 10000}, {"variation": 1, "weight": 90000}]}}
R20 = {"rollout": {"kind": "rollout", "variations": [{"variation": 0, "weight": 20000}, {"variation": 1, "weight": 80000}]}}
R50 = {"rollout": {"kind": "rollout", "variations": [{"variation": 0, "weight": 50000}, {"variation": 1, "weight": 50000}]}}
# buckets (salt new-checkout): user-1 65341, user-2 519, user-3 47924, user-4 8129, user-5 19804
cases += [
    {"name": "rollout 10%: user-1 (bucket 65341) gets false", "flag": flag(fallthrough=R10), "user": {"id": "user-1"}, "expected": res(False, 1, "FALLTHROUGH")},
    {"name": "rollout 10%: user-2 (bucket 519) gets true", "flag": flag(fallthrough=R10), "user": {"id": "user-2"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "rollout 10%: user-4 (bucket 8129) gets true", "flag": flag(fallthrough=R10), "user": {"id": "user-4"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "rollout 10%: user-5 (bucket 19804) gets false", "flag": flag(fallthrough=R10), "user": {"id": "user-5"}, "expected": res(False, 1, "FALLTHROUGH")},
    {"name": "rollout 20%: user-5 (bucket 19804) now gets true", "flag": flag(fallthrough=R20), "user": {"id": "user-5"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "rollout 20%: user-2 stays true", "flag": flag(fallthrough=R20), "user": {"id": "user-2"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "salt changes bucket: user-1 with salt other-flag (43570)", "flag": flag(fallthrough=R50, salt="other-flag"), "user": {"id": "user-1"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "salt defaults to key: user-1 (65341)", "flag": flag(fallthrough=R50, salt=""), "user": {"id": "user-1"}, "expected": res(False, 1, "FALLTHROUGH")},
    {"name": "weights below 100000 fall to last variation", "flag": flag(fallthrough={"rollout": {"kind": "rollout", "variations": [{"variation": 1, "weight": 10000}, {"variation": 0, "weight": 10000}]}}), "user": {"id": "user-1"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "bucket_by attribute (acme-corp 47498)", "flag": flag(fallthrough={"rollout": {"kind": "rollout", "bucket_by": "company", "variations": [{"variation": 0, "weight": 50000}, {"variation": 1, "weight": 50000}]}}), "user": {"id": "user-1", "company": "acme-corp"}, "expected": res(True, 0, "FALLTHROUGH")},
    {"name": "bucket_by missing attribute uses bucket 0", "flag": flag(fallthrough={"rollout": {"kind": "rollout", "bucket_by": "company", "variations": [{"variation": 1, "weight": 1}, {"variation": 0, "weight": 99999}]}}), "user": {"id": "user-1"}, "expected": res(False, 1, "FALLTHROUGH")},
    {"name": "bucket_by prototype property uses bucket 0", "flag": flag(fallthrough={"rollout": {"kind": "rollout", "bucket_by": "toString", "variations": [{"variation": 1, "weight": 1}, {"variation": 0, "weight": 99999}]}}), "user": {"id": "user-1"}, "expected": res(False, 1, "FALLTHROUGH")},
    {"name": "rule serving a rollout", "flag": flag(rules=[rule("ca", [clause("country", "in", ["CA"])], R10)]), "user": {"id": "user-2", "country": "CA"}, "expected": res(True, 0, "RULE_MATCH", rule_index=0, rule_id="ca")},
]
EXP = {"key": "checkout-test", "version": 3, "kind": "string", "on": True, "variations": ["control", "one-page", "two-page"],
       "off_variation": 0, "targets": [], "rules": [],
       "fallthrough": {"rollout": {"kind": "experiment", "variations": [{"variation": 0, "weight": 33334}, {"variation": 1, "weight": 33333}, {"variation": 2, "weight": 33333}]}},
       "salt": "exp", "client_side": True}
# buckets (salt exp): a 96885, b 7089, c 75760, d 50338
cases += [
    {"name": "experiment fallthrough: b (7089) control", "flag": EXP, "user": {"id": "b"}, "expected": res("control", 0, "FALLTHROUGH", in_experiment=True)},
    {"name": "experiment fallthrough: d (50338) one-page", "flag": EXP, "user": {"id": "d"}, "expected": res("one-page", 1, "FALLTHROUGH", in_experiment=True)},
    {"name": "experiment fallthrough: a (96885) two-page", "flag": EXP, "user": {"id": "a"}, "expected": res("two-page", 2, "FALLTHROUGH", in_experiment=True)},
    {"name": "experiment off is not in experiment", "flag": {**EXP, "on": False}, "user": {"id": "a"}, "expected": res("control", 0, "OFF")},
    {"name": "experiment in rule", "flag": {**EXP, "fallthrough": {"variation": 0}, "rules": [rule("beta", [clause("groups", "in", ["beta"])], EXP["fallthrough"])]}, "user": {"id": "c", "groups": ["beta"]}, "expected": res("two-page", 2, "RULE_MATCH", rule_index=0, rule_id="beta", in_experiment=True)},
    {"name": "experiment targeted user is not in experiment", "flag": {**EXP, "targets": [{"variation": 1, "values": ["a"]}]}, "user": {"id": "a"}, "expected": res("one-page", 1, "TARGET_MATCH")},
    {"name": "json variations", "flag": flag(kind="json", variations=[{"color": "red", "size": [1, 2]}, {"color": "blue"}], fallthrough={"variation": 0}), "user": {"id": "u"}, "expected": res({"color": "red", "size": [1, 2]}, 0, "FALLTHROUGH")},
    {"name": "number variations", "flag": flag(kind="number", variations=[10, 25.5, 0], rules=[rule("pro", [clause("plan", "in", ["pro"])], {"variation": 1})], fallthrough={"variation": 2}), "user": {"id": "u", "plan": "pro"}, "expected": res(25.5, 1, "RULE_MATCH", rule_index=0, rule_id="pro")},
]

names = [c["name"] for c in cases]
assert len(names) == len(set(names)), "duplicate case names"
(out / "evaluation.json").write_text(json.dumps({"description": "Shared evaluation conformance cases. See spec/evaluation.md.", "cases": cases}, indent=2, ensure_ascii=False) + "\n")

bucket_cases = [
    {"salt": "new-checkout", "value": "user-1", "bucket": 65341},
    {"salt": "new-checkout", "value": "user-2", "bucket": 519},
    {"salt": "other-flag", "value": "user-1", "bucket": 43570},
    {"salt": "s", "value": "42", "bucket": 73565},
    {"salt": "s", "value": 42, "bucket": 73565},
    {"salt": "s", "value": 42.0, "bucket": 73565},
    {"salt": "s", "value": -7, "bucket": 38140},
    {"salt": "s", "value": 42.5, "bucket": 0},
    {"salt": "s", "value": 9007199254740992, "bucket": 0},
    {"salt": "s", "value": True, "bucket": 0},
    {"salt": "s", "value": None, "bucket": 0},
    {"salt": "s", "value": ["a"], "bucket": 0},
    {"salt": "s", "value": "", "bucket": 71360},
    {"salt": "s", "value": "héllo", "bucket": 275},
    {"salt": "s", "value": "user-🚀", "bucket": 92032},
]
(out / "bucketing.json").write_text(json.dumps({"description": "bucket(salt, value) conformance cases. See spec/evaluation.md#percentage-rollouts-bucketing.", "cases": bucket_cases}, indent=2, ensure_ascii=False) + "\n")
print(len(cases), "evaluation cases,", len(bucket_cases), "bucketing cases")
