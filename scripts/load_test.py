"""Fan-out load test: N concurrent SDK streams, one flag change, how fast does it reach all of them?

Usage:
  python scripts/seed_demo.py              # or use your own org
  python scripts/load_test.py --email E --password P --connections 1000 --changes 5

Opens N streaming connections (like N running SDK instances), then makes flag changes
through the API and records, for every connection, the time from the API call
returning to the patch arriving. Requires httpx.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def stream(client: httpx.AsyncClient, url: str, key: str, ready: asyncio.Event,
                 counter: list, arrivals: dict[int, list[float]], stop: asyncio.Event) -> None:
    try:
        async with client.stream("GET", f"{url}/sdk/v1/stream", headers={"Authorization": key},
                                 timeout=None) as r:
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event = line[7:].strip()
                elif line.startswith("data:") and event == "put":
                    counter[0] += 1
                    if counter[0] == counter[1]:
                        ready.set()
                elif line.startswith("data:") and event == "patch":
                    v = json.loads(line[6:])["env_version"]
                    arrivals.setdefault(v, []).append(time.perf_counter())
                if stop.is_set():
                    return
    except Exception as e:  # noqa: BLE001
        counter[2] += 1
        if counter[2] <= 3:
            print("stream error:", repr(e))


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--connections", type=int, default=500)
    p.add_argument("--changes", type=int, default=5)
    p.add_argument("--env", default="development")
    a = p.parse_args()

    limits = httpx.Limits(max_connections=a.connections + 20, max_keepalive_connections=0)
    async with httpx.AsyncClient(limits=limits, timeout=30) as http:
        tok = (await http.post(f"{a.api}/api/auth/login",
                               json={"email": a.email, "password": a.password})).json()["token"]
        H = {"Authorization": f"Bearer {tok}"}
        org = (await http.get(f"{a.api}/api/me", headers=H)).json()["orgs"][0]["id"]
        base = f"{a.api}/api/orgs/{org}/projects/default"
        key = (await http.post(f"{base}/environments/{a.env}/keys/rotate", headers=H,
                               json={"kind": "server", "grace_seconds": 3600})).json()["value"]
        flags = (await http.get(f"{base}/flags", headers=H)).json()
        flag = flags[0]["key"]

        ready, stop = asyncio.Event(), asyncio.Event()
        counter = [0, a.connections, 0]  # connected, target, errors
        arrivals: dict[int, list[float]] = {}
        t0 = time.perf_counter()
        tasks = [asyncio.create_task(stream(http, a.api, key, ready, counter, arrivals, stop))
                 for _ in range(a.connections)]
        await asyncio.wait_for(ready.wait(), timeout=120)
        print(f"{a.connections} streams connected in {time.perf_counter() - t0:.1f}s")
        health = (await http.get(f"{a.api}/health")).json()
        print("server reports", health["stream_connections"], "stream connections")

        latencies: list[float] = []
        for _ in range(a.changes):
            cfg = (await http.get(f"{base}/flags/{flag}", headers=H)).json()["environments"][a.env]
            body = {k: cfg[k] for k in ("on", "off_variation", "targets", "rules", "fallthrough")}
            body["on"] = not body["on"]
            r = await http.put(f"{base}/flags/{flag}/environments/{a.env}", json=body,
                               headers={**H, "If-Match": f'"{cfg["version"]}"'})
            sent = time.perf_counter()
            r.raise_for_status()
            env_version = (await http.get(f"{a.api}/sdk/v1/flags",
                                          headers={"Authorization": key})).json()["env_version"]
            deadline = time.perf_counter() + 10
            while len(arrivals.get(env_version, [])) < a.connections and time.perf_counter() < deadline:
                await asyncio.sleep(0.01)
            got = arrivals.get(env_version, [])
            latencies.extend((t - sent) * 1000 for t in got)
            print(f"change v{env_version}: delivered to {len(got)}/{a.connections} streams, "
                  f"last after {(max(got) - sent) * 1000 if got else float('nan'):.0f} ms")
        stop.set()
        for t in tasks:
            t.cancel()

    latencies.sort()
    q = lambda f: latencies[min(len(latencies) - 1, int(f * len(latencies)))]  # noqa: E731
    print(f"\npropagation latency over {len(latencies)} deliveries: p50 {q(0.5):.0f} ms, "
          f"p95 {q(0.95):.0f} ms, p99 {q(0.99):.0f} ms, max {latencies[-1]:.0f} ms, "
          f"mean {statistics.mean(latencies):.0f} ms; stream errors: {counter[2]}")


if __name__ == "__main__":
    asyncio.run(main())
