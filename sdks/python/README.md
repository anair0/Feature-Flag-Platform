# featureflags (Python SDK)

Server-side SDK: downloads targeting rules, evaluates locally (no network per call), and
receives changes over a streaming connection. No dependencies, Python 3.9+.

```python
from featureflags import FlagClient

client = FlagClient("srv-...", base_url="https://flags.example.com")   # waits up to 5 s, never raises

user = {"id": "user-123", "country": "CA", "plan": "pro"}
if client.bool("new-checkout", user, default=False):
    ...

detail = client.variation_detail("new-checkout", user, False)
detail.reason   # {"kind": "RULE_MATCH", "rule_index": 0, "rule_id": "canada"}

client.track(user, "purchase", 49.99)   # metric event for experiments
client.add_listener(lambda key: print(key, "changed"))
client.close()
```

Typed accessors: `bool`, `string`, `number`, `json`. A value of the wrong type returns the
default with reason `WRONG_TYPE`.

| Option | Default | |
|---|---|---|
| `stream` | `True` | `False` = poll every `poll_interval` seconds |
| `init_timeout` | `5.0` | max seconds the constructor waits for data (0 = don't wait) |
| `send_events` | `True` | exposure + `track()` events, batched every `events_flush_interval` |
| `offline` / `bootstrap` | | no network; serve a given `{"env_version", "flags"}` snapshot (tests) |

**Guarantees:** no method raises; if the server is unreachable the client serves the last
known flags (or your defaults) and reconnects with backoff; missed updates are detected by
version and re-synced. See `spec/streaming.md`.

```bash
pip install -e ".[dev]" && pytest
```
