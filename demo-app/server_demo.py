"""Terminal demo of the Python SDK: watch flag values change live as you edit them.

Usage: python demo-app/server_demo.py <server-sdk-key> [--api http://localhost:8000]
"""

import argparse
import sys
import time

from featureflags import FlagClient

USERS = [
    {"id": "user-1", "country": "US"},
    {"id": "user-2", "country": "US"},
    {"id": "user-3", "country": "CA"},
    {"id": "user-4", "country": "GB"},
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("sdk_key")
    p.add_argument("--api", default="http://localhost:8000")
    args = p.parse_args()

    changed_at: dict[str, float] = {}
    with FlagClient(args.sdk_key, base_url=args.api) as client:
        client.add_listener(lambda key: changed_at.__setitem__(key, time.monotonic()))
        if not client.is_ready():
            print("Could not reach the server; serving defaults (the app keeps working).")
        while True:
            rows = []
            for u in USERS:
                d = client.variation_detail("new-checkout", u, False)
                why = d.reason.get("rule_id") or d.reason.get("error_kind") or d.reason["kind"]
                rows.append(f"  {u['id']:>7} ({u['country']}): {str(d.value):5}  [{why}]")
            age = time.monotonic() - changed_at["new-checkout"] if "new-checkout" in changed_at else None
            sys.stdout.write("\033[2J\033[H")  # clear screen
            print("new-checkout, evaluated locally by the Python SDK (no network per call)\n")
            print("\n".join(rows))
            if age is not None:
                print(f"\n  last change received {age:.1f}s ago")
            time.sleep(0.25)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
