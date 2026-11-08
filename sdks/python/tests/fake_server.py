"""A tiny in-process stand-in for the flag server's SDK endpoints."""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeServer:
    def __init__(self, port: int = 0, flags: dict | None = None, env_version: int = 1):
        self.flags = flags or {}
        self.env_version = env_version
        self.snapshot_requests = 0
        self.stream_connections = 0
        self.events: list[dict] = []
        self.auth_headers: list[str] = []
        self._streams: list[queue.Queue] = []
        self._stop = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # quiet
                pass

            def do_GET(self):
                owner.auth_headers.append(self.headers.get("Authorization", ""))
                if self.path == "/sdk/v1/flags":
                    owner.snapshot_requests += 1
                    self._json({"env_version": owner.env_version, "flags": owner.flags})
                elif self.path == "/sdk/v1/stream":
                    owner.stream_connections += 1
                    q: queue.Queue = queue.Queue()
                    owner._streams.append(q)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    try:
                        self._sse("put", {"env_version": owner.env_version, "flags": owner.flags})
                        while not owner._stop.is_set():
                            try:
                                item = q.get(timeout=0.05)
                            except queue.Empty:
                                continue
                            if item is None:
                                return
                            self._sse(*item)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        owner._streams.remove(q)
                else:
                    self.send_error(404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.events.extend(body["events"])
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _json(self, obj):
                raw = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _sse(self, event, data):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()

        ThreadingHTTPServer.allow_reuse_address = True
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def send(self, event: str, data: dict) -> None:
        for q in list(self._streams):
            q.put((event, data))

    def patch(self, key: str, flag: dict | None, env_version: int | None = None) -> None:
        self.env_version = env_version if env_version is not None else self.env_version + 1
        if flag is None:
            self.flags.pop(key, None)
        else:
            self.flags[key] = flag
        self.send("patch", {"env_version": self.env_version, "key": key, "flag": flag})

    def stop(self) -> None:
        self._stop.set()
        for q in list(self._streams):
            q.put(None)
        self.httpd.shutdown()
        self.httpd.server_close()
