# Evaluation

`evaluate(flag, user) -> {value, variation_index, reason}`

Every implementation (the Python SDK, the TypeScript SDK, and the server's
browser-evaluation endpoint, which reuses the Python engine) **must** produce
identical output for every case in `test-vectors/evaluation.json` and
`test-vectors/bucketing.json`.

## Order of checks (fixed)

1. **Invalid user.** If `user` is not an object, or `user.id` is not a
   non-empty string, the result is `ERROR / USER_NOT_SPECIFIED`.
2. **Off.** If `on` is not `true`, the result is `off_variation`, reason
   `OFF`. If `off_variation` is `null`, both value and index are `null` (the
   SDK substitutes the caller's default).
3. **Individual targets.** The first target whose `values` contains `user.id`
   gives that variation, reason `TARGET_MATCH`.
4. **Rules**, in order. The first rule whose clauses all match is served,
   reason `RULE_MATCH` with `rule_index` and `rule_id`. A rule with zero
   clauses never matches.
5. **Fallthrough**, reason `FALLTHROUGH`.

When a referenced variation index is not an integer within `variations`, or
a rollout has no variations, the result is `ERROR / MALFORMED_FLAG` with value
and index `null`.

## Result

```json
{ "value": true, "variation_index": 0, "reason": { "kind": "RULE_MATCH", "rule_index": 0, "rule_id": "canada" } }
```

Reason shapes:

| kind | extra fields |
|---|---|
| `OFF` | none |
| `TARGET_MATCH` | none |
| `RULE_MATCH` | `rule_index`, `rule_id`, and `in_experiment: true` if served by an experiment rollout |
| `FALLTHROUGH` | `in_experiment: true` if served by an experiment rollout |
| `ERROR` | `error_kind` |

`in_experiment` is **omitted** (not `false`) when it doesn't apply.

Engine error kinds: `USER_NOT_SPECIFIED`, `MALFORMED_FLAG`. SDKs add
`FLAG_NOT_FOUND`, `WRONG_TYPE`, `CLIENT_NOT_READY` and `EXCEPTION`; in every
one of those cases the SDK returns the caller's default value.

## Clauses

Let `u = user[attribute]`.

- If `u` is missing or `null`, the clause **does not match**, and `negate` is
  *not* applied. A rule written as "country is not CA" should not match users
  who have no country.
- If `u` is an array, the clause matches when any non-null element matches.
  Otherwise it matches when `u` matches.
- A single value matches when `op(u, v)` is true for **any** `v` in `values`.
- `negate: true` inverts the result (except in the missing-attribute case
  above).
- An unknown operator never matches and is not an error. This keeps older
  SDKs working when the server adds operators.

### Operators

Type mismatches never match. Booleans are **not** numbers.

| op | `u` and `v` | true when |
|---|---|---|
| `in` | scalars of the same JSON type | `u == v` (strings case-sensitive, numbers numerically) |
| `starts_with` | strings | `u` starts with `v` |
| `ends_with` | strings | `u` ends with `v` |
| `contains` | strings | `v` is a substring of `u` |
| `lt` `lte` `gt` `gte` | numbers | numeric comparison `u <op> v` |
| `semver_eq` `semver_lt` `semver_gt` | semver strings | semantic-version comparison of `u` against `v` |

There is deliberately **no regex operator**: Python and JavaScript regex
dialects differ, which would break the "identical answers" guarantee.

### Semver

Accepted: `MAJOR[.MINOR[.PATCH]][-PRERELEASE][+BUILD]`, where each number is
a run of digits. Missing minor/patch count as `0`. Build metadata is ignored.
Anything else (including a leading `v`) fails to parse, and the clause does
not match. Precedence follows semver.org §11: compare major, minor and patch
numerically. A version with a prerelease sorts below the same version without
one. Prerelease identifiers are compared dot-by-dot: numeric identifiers
numerically, numeric < alphanumeric, alphanumerics by ASCII, and a shorter set
sorts lower when all its identifiers are equal to the other's.

## Percentage rollouts (bucketing)

```
attr   = rollout.bucket_by or "id"
raw    = user[attr]
s      = raw                     if raw is a string
       = decimal integer string  if raw is a number with an integral value, |raw| <= 2^53 - 1, not a boolean
       = (none)                  otherwise
bucket = 0                                            if s is none
       = int(sha1_hex(utf8(salt + "." + s))[0:8], 16) mod 100000   otherwise
```

`salt` is `flag.salt`, or `flag.key` if `salt` is missing or empty.

Walk `rollout.variations` in order, keeping a running sum of `weight`. Serve
the first variation where `bucket < sum`. If none qualifies (weights sum to
less than 100000), serve the **last** listed variation.

Properties this guarantees:

- **Sticky:** a given user and flag always land in the same bucket.
- **Monotonic:** raising variation 0's weight from 10% to 20% only moves users
  *into* variation 0. Nobody already in it leaves.
- **Independent across flags:** different salts produce uncorrelated buckets,
  so the same 10% of users don't get every experiment.
