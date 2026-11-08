# Delivery protocol

## Keys

| Key | Prefix | Secret? | Can do |
|---|---|---|---|
| Server SDK key | `srv-` | yes | download full rules, stream patches, send events |
| Client-side ID | `cli-` | no (shipped to browsers) | ask for *evaluated values* of `client_side` flags, stream change pings, send events |

Server SDKs send `Authorization: <key>`. Browser SDKs send the client-side ID
in the `X-Client-Id` header or the `client_id` query parameter.

## Server SDKs

### `GET /sdk/v1/flags`

Returns `{"env_version": N, "flags": {key: config}}`.

### `GET /sdk/v1/stream` (Server-Sent Events)

```
event: put
data: {"env_version": 42, "flags": {...}}

event: patch
data: {"env_version": 43, "key": "new-checkout", "flag": {...config...}}

event: patch
data: {"env_version": 44, "key": "old-flag", "flag": null}     <- archived/deleted

: heartbeat                                                     <- every 15s
```

The client rules:

1. On connect the server always sends `put`, and the client replaces its whole store.
2. For a `patch`:
   - if `env_version <= current`, ignore it (stale or duplicate).
   - if `env_version == current + 1`, apply it and set `current = env_version`.
   - if `env_version > current + 1`, an update was missed, so re-fetch
     `GET /sdk/v1/flags` and replace the store.
3. If nothing (data or heartbeat) arrives for 45 seconds, treat the connection as dead.
4. On any disconnect, keep serving the last known flags and reconnect with
   exponential backoff (1s doubling up to 30s, with ±50% jitter). Reset the
   backoff after a connection has stayed healthy for 60 seconds.

## Browser SDKs

### `POST /sdk/v1/evaluate`

Body `{"user": {...}}`. Returns
`{"env_version": N, "flags": {key: {value, variation_index, reason}}}` for
every `client_side` flag. Full rules are never sent to the browser.

### `GET /sdk/v1/client-stream?client_id=...`

Sends `event: change` with `data: {"env_version": N}` (and no flag data) when
anything in the environment changes. The browser SDK then calls `evaluate`
again.

## Events

### `POST /sdk/v1/events`

```json
{ "events": [
  { "kind": "exposure", "user_id": "u1", "flag_key": "new-checkout", "variation_index": 1, "timestamp": 1730000000000 },
  { "kind": "custom", "user_id": "u1", "metric_key": "purchase", "value": 49.99, "timestamp": 1730000000500 }
]}
```

Exposures are sent only for evaluations whose reason has `in_experiment: true`.
SDKs dedupe them per `(user, flag, variation)`, batch them, and drop them
(never block) when their buffer is full.
