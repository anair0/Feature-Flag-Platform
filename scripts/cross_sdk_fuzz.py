"""Differential test: random flags x random users, Python engine vs TypeScript engine.

The shared vectors check cases someone thought of; this checks thousands nobody did.
Usage: python scripts/cross_sdk_fuzz.py [--cases N] [--seed S]
(requires `npm run build` in sdks/typescript and the Python SDK installed)
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdks" / "python" / "src"))
from featureflags.evaluation import evaluate  # noqa: E402

ATTRS = ["country", "plan", "age", "app_version", "groups", "email", "beta", "score", "id",
         "constructor", "toString", "missing"]
STRINGS = ["CA", "US", "ca", "pro", "free", "", "a", "jo@acme.com", "acme", "1", "2.4.0",
           "2.4.0-beta.1", "1.0.0-alpha.1", "v1.0.0", "10.0", "héllo", "🚀"]
OPS = ["in", "starts_with", "ends_with", "contains", "lt", "lte", "gt", "gte", "semver_eq",
       "semver_lt", "semver_gt", "bogus"]


def scalar(r: random.Random):
    return r.choice([
        lambda: r.choice(STRINGS),
        lambda: r.randint(-5, 50),
        lambda: r.choice([0.5, 1.0, 2.25, 18.0, -0.0]),
        lambda: r.choice([True, False]),
    ])()


def user(r: random.Random, f: dict):
    if r.random() < 0.03:
        u: dict = {}
    else:
        u = {"id": "" if r.random() < 0.03 else f"user-{r.randint(0, 999)}"}
    for a in r.sample(ATTRS[:-3], r.randint(0, 6)):
        if a == "id":
            continue
        u[a] = [scalar(r) for _ in range(r.randint(0, 3))] if r.random() < 0.2 else scalar(r)
        if r.random() < 0.05:
            u[a] = None
    # Bias toward matching: copy some clause values from the flag into the user.
    for rule in f["rules"]:
        for c in rule["clauses"]:
            if c["attribute"] != "id" and r.random() < 0.5:
                u[c["attribute"]] = r.choice(c["values"])
    return u


def serve(r: random.Random, n: int):
    if r.random() < 0.5:
        return {"variation": r.randint(0, n) if r.random() < 0.05 else r.randint(0, n - 1)}
    k = r.randint(1, n)
    idx = r.sample(range(n), k)
    cuts = sorted(r.randint(0, 100_000) for _ in range(k - 1))
    weights = [b - a for a, b in zip([0, *cuts], [*cuts, 100_000])]
    if r.random() < 0.1:
        weights[-1] = max(0, weights[-1] - r.randint(0, 50_000))
    ro = {"kind": r.choice(["rollout", "experiment"]),
          "variations": [{"variation": i, "weight": w} for i, w in zip(idx, weights)]}
    if r.random() < 0.3:
        ro["bucket_by"] = r.choice(["id", "country", "age", "score", "missing", "toString"])
    return {"rollout": ro}


def flag(r: random.Random):
    n = r.randint(2, 4)
    return {
        "key": r.choice(["f", "new-checkout", "exp"]), "version": 1, "kind": "string",
        "on": r.random() < 0.85,
        "variations": [f"v{i}" for i in range(n)],
        "off_variation": r.choice([None, 0, 1]),
        "targets": [{"variation": r.randint(0, n - 1),
                     "values": [f"user-{r.randint(0, 999)}" for _ in range(r.randint(0, 20))]}
                    for _ in range(r.randint(0, 2))],
        "rules": [{"id": f"r{i}",
                   "clauses": [{"attribute": r.choice(ATTRS), "op": r.choice(OPS),
                                "values": [scalar(r) for _ in range(r.randint(1, 3))],
                                "negate": r.random() < 0.2}
                               for _ in range(r.randint(0, 3))],
                   "serve": serve(r, n)} for i in range(r.randint(0, 4))],
        "fallthrough": serve(r, n),
        "salt": r.choice(["", "s1", "new-checkout"]),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=int, default=5000)
    p.add_argument("--seed", type=int, default=12345)
    args = p.parse_args()
    r = random.Random(args.seed)
    flags = [flag(r) for _ in range(args.cases)]
    cases = [{"flag": f, "user": user(r, f)} for f in flags]
    for c in cases:
        c["expected"] = evaluate(c["flag"], c["user"]).to_dict()

    js = """
      import { readFileSync } from "node:fs";
      import { evaluate } from "./dist/evaluation.js";
      const cases = JSON.parse(readFileSync(process.argv[1], "utf8"));
      const bad = [];
      cases.forEach((c, i) => {
        const got = evaluate(c.flag, c.user);
        if (JSON.stringify(got) !== JSON.stringify(c.expected)) bad.push({ i, got, ...c });
      });
      console.log(JSON.stringify({ total: cases.length, mismatches: bad.slice(0, 5), count: bad.length }));
    """
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cases, f)
    out = subprocess.run(["node", "--input-type=module", "-e", js, f.name], capture_output=True,
                         text=True, cwd=ROOT / "sdks" / "typescript", check=True)
    result = json.loads(out.stdout)
    kinds: dict[str, int] = {}
    for c in cases:
        kinds[c["expected"]["reason"]["kind"]] = kinds.get(c["expected"]["reason"]["kind"], 0) + 1
    print(f"{result['total']} random cases, reasons covered: {kinds}")
    if result["count"]:
        print(f"MISMATCHES: {result['count']}")
        print(json.dumps(result["mismatches"], indent=2, ensure_ascii=False))
        return 1
    print("Python and TypeScript engines agree on every case.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
