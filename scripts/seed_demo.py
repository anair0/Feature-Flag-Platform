"""Create a demo org with flags ready for the demo app, and print the keys.

Usage: python scripts/seed_demo.py [--api http://localhost:8000]
Writes demo-app/.env.local (VITE_CLIENT_ID) and prints the server key for
demo-app/server_demo.py. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def call(api: str, method: str, path: str, body=None, token: str | None = None, headers=None):
    req = urllib.request.Request(api + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()}") from None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--email", default=f"demo-{int(time.time())}@example.com")
    p.add_argument("--password", default="demo-password")
    args = p.parse_args()
    api = args.api.rstrip("/")

    signup = call(api, "POST", "/api/auth/signup", {"email": args.email, "password": args.password,
                                                   "name": "Demo PM", "org_name": "Demo Store Inc"})
    token, org = signup["token"], signup["org_id"]
    base = f"/api/orgs/{org}/projects/default"

    call(api, "POST", f"{base}/flags", {"key": "new-checkout", "name": "New checkout",
                                        "description": "One-page checkout", "client_side": True},
         token)
    call(api, "POST", f"{base}/flags", {"key": "promo-banner", "name": "Promo banner",
                                        "kind": "string", "client_side": True,
                                        "variations": ["", "Free shipping this week!",
                                                       "20% off for pro members"]}, token)
    rule = {"id": "canada", "description": "Launch in Canada first",
            "clauses": [{"attribute": "country", "op": "in", "values": ["CA"]}],
            "serve": {"variation": 0}}
    rollout = {"rollout": {"kind": "rollout", "variations": [
        {"variation": 0, "weight": 10000}, {"variation": 1, "weight": 90000}]}}
    for env in ("development", "production"):
        flag = call(api, "GET", f"{base}/flags/new-checkout", token=token)
        version = flag["environments"][env]["version"]
        call(api, "PUT", f"{base}/flags/new-checkout/environments/{env}",
             {"on": env == "development", "off_variation": 1, "targets": [], "rules": [rule],
              "fallthrough": rollout}, token, {"If-Match": f'"{version}"'})

    server = call(api, "POST", f"{base}/environments/development/keys/rotate", {"kind": "server"},
                  token)["value"]
    keys = call(api, "GET", f"{base}/environments/development/keys", token=token)
    client_id = next(k["value"] for k in keys if k["kind"] == "client")
    (ROOT / "demo-app" / ".env.local").write_text(f"VITE_CLIENT_ID={client_id}\n")

    print(f"""
Demo ready.
  Dashboard login:  {args.email} / {args.password}
  Server SDK key (development):  {server}
  Client-side ID (development):  {client_id}   (written to demo-app/.env.local)

Next:
  cd demo-app && npm install && npm run dev        # http://localhost:5174
  python demo-app/server_demo.py {server}
Then open the dashboard, go to new-checkout -> Development, and flip it.
""")


if __name__ == "__main__":
    main()
