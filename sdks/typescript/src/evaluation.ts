/**
 * Pure flag evaluation. A line-by-line port of sdks/python/src/featureflags/evaluation.py,
 * implementing spec/evaluation.md. Both must pass spec/test-vectors/*.json.
 *
 * JavaScript pitfalls handled explicitly (Python doesn't have them):
 * - user["constructor"] etc. resolve through the prototype: attributes are own properties only.
 * - typeof true !== "number" already, but integers vs floats are the same type: bucketing uses
 *   Number.isInteger to match Python's int/float.is_integer() handling.
 */
import { sha1Hex } from "./sha1.js";
import type { EvaluationDetail, FlagConfig, JsonValue, Reason } from "./types.js";

export const BUCKET_SCALE = 100_000;

class Malformed extends Error {}

type Dict = Record<string, unknown>;

const isDict = (x: unknown): x is Dict => typeof x === "object" && x !== null && !Array.isArray(x);
const isNumber = (x: unknown): x is number => typeof x === "number";
const isString = (x: unknown): x is string => typeof x === "string";
const own = (o: Dict, key: unknown): unknown =>
  typeof key === "string" && Object.prototype.hasOwnProperty.call(o, key) ? o[key] : undefined;

function sameScalar(a: unknown, b: unknown): boolean {
  const ta = typeof a;
  if (ta !== typeof b) return false;
  return (ta === "boolean" || ta === "number" || ta === "string") && a === b;
}

// ------------------------------------------------------------------------ semver

const SEMVER =
  /^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$/;

type Semver = [bigint, bigint, bigint, string[]];

export function parseSemver(s: unknown): Semver | null {
  if (!isString(s)) return null;
  const m = SEMVER.exec(s);
  if (!m) return null;
  return [BigInt(m[1]), BigInt(m[2] ?? 0), BigInt(m[3] ?? 0), m[4] ? m[4].split(".") : []];
}

const isDigits = (s: string) => /^\d+$/.test(s);
const cmp = <T>(a: T, b: T) => (a > b ? 1 : a < b ? -1 : 0);

function comparePrerelease(a: string[], b: string[]): number {
  if (!a.length && !b.length) return 0;
  if (!a.length) return 1;
  if (!b.length) return -1;
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const an = isDigits(a[i]);
    const bn = isDigits(b[i]);
    let c: number;
    if (an && bn) c = cmp(BigInt(a[i]), BigInt(b[i]));
    else if (an) c = -1;
    else if (bn) c = 1;
    else c = cmp(a[i], b[i]); // JS string comparison is by UTF-16 code unit == ASCII here
    if (c) return c;
  }
  return cmp(a.length, b.length);
}

export function compareSemver(a: Semver, b: Semver): number {
  for (let i = 0; i < 3; i++) {
    const c = cmp(a[i] as bigint, b[i] as bigint);
    if (c) return c;
  }
  return comparePrerelease(a[3], b[3]);
}

const semverOp = (pred: (c: number) => boolean) => (u: unknown, v: unknown) => {
  const pu = parseSemver(u);
  const pv = parseSemver(v);
  return pu !== null && pv !== null && pred(compareSemver(pu, pv));
};
const strOp = (fn: (u: string, v: string) => boolean) => (u: unknown, v: unknown) =>
  isString(u) && isString(v) && fn(u, v);
const numOp = (fn: (u: number, v: number) => boolean) => (u: unknown, v: unknown) =>
  isNumber(u) && isNumber(v) && fn(u, v);

export const OPERATORS: Record<string, (u: unknown, v: unknown) => boolean> = {
  in: sameScalar,
  starts_with: strOp((u, v) => u.startsWith(v)),
  ends_with: strOp((u, v) => u.endsWith(v)),
  contains: strOp((u, v) => u.includes(v)),
  lt: numOp((u, v) => u < v),
  lte: numOp((u, v) => u <= v),
  gt: numOp((u, v) => u > v),
  gte: numOp((u, v) => u >= v),
  semver_eq: semverOp((c) => c === 0),
  semver_lt: semverOp((c) => c < 0),
  semver_gt: semverOp((c) => c > 0),
};

// ---------------------------------------------------------------------- matching

export function clauseMatches(clause: Dict, user: Dict): boolean {
  const op = own(OPERATORS as Dict, clause.op) as ((u: unknown, v: unknown) => boolean) | undefined;
  if (!op) return false;
  const u = own(user, clause.attribute);
  if (u === undefined || u === null) return false;
  const values = Array.isArray(clause.values) ? clause.values : [];
  const candidates = Array.isArray(u) ? u.filter((x) => x !== null && x !== undefined) : [u];
  const matched = candidates.some((c) => values.some((v) => op(c, v)));
  return clause.negate ? !matched : matched;
}

function ruleMatches(rule: Dict, user: Dict): boolean {
  const clauses = Array.isArray(rule.clauses) ? rule.clauses : [];
  return clauses.length > 0 && clauses.every((c) => isDict(c) && clauseMatches(c, user));
}

// --------------------------------------------------------------------- bucketing

function bucketString(raw: unknown): string | null {
  if (isString(raw)) return raw;
  if (isNumber(raw) && Number.isInteger(raw) && Math.abs(raw) <= Number.MAX_SAFE_INTEGER) {
    return String(raw);
  }
  return null;
}

/** The user's bucket in [0, 100000). */
export function bucket(salt: string, value: unknown): number {
  const s = bucketString(value);
  if (s === null) return 0;
  return parseInt(sha1Hex(`${salt}.${s}`).slice(0, 8), 16) % BUCKET_SCALE;
}

// -------------------------------------------------------------------- evaluation

function variation(flag: Dict, index: unknown): [JsonValue, number] {
  const variations = flag.variations;
  if (
    !Number.isInteger(index) ||
    !Array.isArray(variations) ||
    (index as number) < 0 ||
    (index as number) >= variations.length
  ) {
    throw new Malformed();
  }
  return [variations[index as number] as JsonValue, index as number];
}

function serve(flag: Dict, s: unknown, user: Dict): [JsonValue, number, boolean] {
  if (!isDict(s)) throw new Malformed();
  if (Object.prototype.hasOwnProperty.call(s, "variation")) {
    const [value, idx] = variation(flag, s.variation);
    return [value, idx, false];
  }
  const rollout = s.rollout;
  if (!isDict(rollout) || !Array.isArray(rollout.variations) || rollout.variations.length === 0) {
    throw new Malformed();
  }
  const salt = (flag.salt as string) || (flag.key as string) || "";
  const b = bucket(salt, own(user, (rollout.bucket_by as string) || "id"));
  const weighted = rollout.variations as Dict[];
  let chosen = weighted[weighted.length - 1];
  let total = 0;
  for (const wv of weighted) {
    total += isNumber(wv.weight) ? wv.weight : 0;
    if (b < total) {
      chosen = wv;
      break;
    }
  }
  const [value, idx] = variation(flag, chosen.variation);
  return [value, idx, rollout.kind === "experiment"];
}

const error = (kind: "USER_NOT_SPECIFIED" | "MALFORMED_FLAG"): EvaluationDetail<JsonValue> => ({
  value: null,
  variation_index: null,
  reason: { kind: "ERROR", error_kind: kind },
});

export function evaluate(flag: FlagConfig | unknown, user: unknown): EvaluationDetail<JsonValue> {
  try {
    if (!isDict(user) || !isString(user.id) || user.id === "") return error("USER_NOT_SPECIFIED");
    if (!isDict(flag)) return error("MALFORMED_FLAG");

    if (flag.on !== true) {
      const off = flag.off_variation;
      if (off === null || off === undefined) {
        return { value: null, variation_index: null, reason: { kind: "OFF" } };
      }
      const [value, idx] = variation(flag, off);
      return { value, variation_index: idx, reason: { kind: "OFF" } };
    }

    for (const target of Array.isArray(flag.targets) ? (flag.targets as Dict[]) : []) {
      if (Array.isArray(target.values) && target.values.includes(user.id)) {
        const [value, idx] = variation(flag, target.variation);
        return { value, variation_index: idx, reason: { kind: "TARGET_MATCH" } };
      }
    }

    const rules = Array.isArray(flag.rules) ? (flag.rules as Dict[]) : [];
    for (let i = 0; i < rules.length; i++) {
      if (isDict(rules[i]) && ruleMatches(rules[i], user)) {
        const [value, idx, exp] = serve(flag, rules[i].serve, user);
        const reason: Reason = {
          kind: "RULE_MATCH",
          rule_index: i,
          rule_id: (rules[i].id as string | undefined) ?? null,
        };
        if (exp) reason.in_experiment = true;
        return { value, variation_index: idx, reason };
      }
    }

    const [value, idx, exp] = serve(flag, flag.fallthrough, user);
    const reason: Reason = { kind: "FALLTHROUGH" };
    if (exp) reason.in_experiment = true;
    return { value, variation_index: idx, reason };
  } catch {
    return error("MALFORMED_FLAG");
  }
}
