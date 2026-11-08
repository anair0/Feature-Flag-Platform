# Flag configuration format

This is the JSON document a server-side SDK downloads for each flag in an
environment. The backend produces it, the SDKs consume it, and the shared test
vectors in `test-vectors/` are written in it. All keys are `snake_case`.

```json
{
  "key": "new-checkout",
  "version": 7,
  "kind": "boolean",
  "on": true,
  "variations": [true, false],
  "off_variation": 1,
  "targets": [
    { "variation": 0, "values": ["user-123", "user-456"] }
  ],
  "rules": [
    {
      "id": "canada",
      "clauses": [
        { "attribute": "country", "op": "in", "values": ["CA"], "negate": false }
      ],
      "serve": { "variation": 0 }
    }
  ],
  "fallthrough": {
    "rollout": {
      "kind": "rollout",
      "bucket_by": "id",
      "variations": [
        { "variation": 0, "weight": 10000 },
        { "variation": 1, "weight": 90000 }
      ]
    }
  },
  "salt": "new-checkout",
  "client_side": false
}
```

| Field | Type | Meaning |
|---|---|---|
| `key` | string | Flag key, unique within a project. |
| `version` | integer | Incremented on every change to this flag in this environment. |
| `kind` | `boolean` \| `string` \| `number` \| `json` | Type of every variation. |
| `on` | boolean | Targeting switch. When `false`, `off_variation` is served. |
| `variations` | array | The possible values. Everything else refers to them by index. |
| `off_variation` | integer \| null | Index served while the flag is off. `null` means "serve the caller's default". |
| `targets` | array | Individual targeting: `{variation, values: [user ids]}`. |
| `rules` | array | Ordered rules. The first matching rule wins. |
| `fallthrough` | serve | What to serve when the flag is on and nothing above matched. |
| `salt` | string | Mixed into the rollout hash. Defaults to the flag key. |
| `client_side` | boolean | Whether browser SDKs (client-side IDs) may evaluate this flag. |

## Serve

A *serve* is exactly one of:

- `{"variation": <index>}`: a fixed variation.
- `{"rollout": {"kind": "rollout" | "experiment", "bucket_by": "<attr>", "variations": [{"variation": i, "weight": w}, ...]}}`

Weights are in thousandths of a percent: `100000` = 100%, `10000` = 10%. The
backend rejects rollouts whose weights don't sum to exactly 100000. `bucket_by`
defaults to `"id"`. `kind: "experiment"` behaves identically to `"rollout"`,
except the evaluation reason carries `"in_experiment": true`. That tells the
SDK to record an exposure event (see `evaluation.md`).

## Clauses

`{"attribute": "<name>", "op": "<operator>", "values": [...], "negate": false}`

A rule matches when **all** of its clauses match. A clause matches when the
user's attribute matches **any** of the clause's `values`. See `evaluation.md`
for each operator's exact semantics.

## User context

```json
{ "id": "user-123", "country": "CA", "plan": "pro", "app_version": "2.4.1", "groups": ["beta"] }
```

`id` is required and must be a non-empty string. Every other top-level key is
an attribute that clauses can reference. Nested objects are not traversed.

## Environment snapshot (`GET /sdk/v1/flags`)

```json
{ "env_version": 42, "flags": { "new-checkout": { ...flag config... } } }
```

`env_version` increases by one with every change to any flag in the
environment. SDKs use it to detect missed stream updates (see `streaming.md`).
