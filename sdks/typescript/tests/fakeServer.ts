import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

export class FakeServer {
  flags: Record<string, any>;
  envVersion: number;
  snapshotRequests = 0;
  evaluateRequests: any[] = [];
  events: any[] = [];
  evaluateDelayMs = 0;
  evaluate: (user: any) => Record<string, any> = () => ({});
  private streams = new Set<ServerResponse>();
  private server!: Server;
  url = "";

  constructor(flags: Record<string, any> = {}, envVersion = 1) {
    this.flags = flags;
    this.envVersion = envVersion;
  }

  async start(port = 0): Promise<this> {
    this.server = createServer((req, res) => void this.route(req, res));
    await new Promise<void>((r) => this.server.listen(port, "127.0.0.1", r));
    this.url = `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`;
    return this;
  }

  get port(): number {
    return (this.server.address() as AddressInfo).port;
  }

  private async body(req: IncomingMessage): Promise<any> {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    return raw ? JSON.parse(raw) : null;
  }

  private async route(req: IncomingMessage, res: ServerResponse) {
    const path = (req.url ?? "").split("?")[0];
    if (path === "/sdk/v1/flags") {
      this.snapshotRequests++;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ env_version: this.envVersion, flags: this.flags }));
    } else if (path === "/sdk/v1/stream" || path === "/sdk/v1/client-stream") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      this.streams.add(res);
      res.on("close", () => this.streams.delete(res));
      if (path === "/sdk/v1/stream") this.write(res, "put", { env_version: this.envVersion, flags: this.flags });
      else this.write(res, "change", { env_version: this.envVersion });
    } else if (path === "/sdk/v1/evaluate") {
      const body = await this.body(req);
      this.evaluateRequests.push(body.user);
      const result = { env_version: this.envVersion, flags: this.evaluate(body.user) };
      const delay = this.evaluateDelayMs;
      setTimeout(() => {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(result));
      }, delay);
    } else if (path === "/sdk/v1/events") {
      this.events.push(...(await this.body(req)).events);
      res.writeHead(202).end();
    } else {
      res.writeHead(404).end();
    }
  }

  private write(res: ServerResponse, event: string, data: unknown) {
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  }

  send(event: string, data: unknown) {
    for (const s of this.streams) this.write(s, event, data);
  }

  patch(key: string, flag: any, envVersion = this.envVersion + 1) {
    this.envVersion = envVersion;
    if (flag === null) delete this.flags[key];
    else this.flags[key] = flag;
    this.send("patch", { env_version: envVersion, key, flag });
  }

  async stop() {
    for (const s of this.streams) s.destroy();
    this.server.closeAllConnections?.();
    await new Promise<void>((r) => this.server.close(() => r()));
  }
}

export const boolFlag = (key = "f", extra: Record<string, any> = {}) => ({
  key, version: 1, kind: "boolean", on: true, variations: [true, false], off_variation: 1,
  targets: [], rules: [], fallthrough: { variation: 0 }, salt: key, client_side: false, ...extra,
});

export async function waitFor(cond: () => boolean, timeoutMs = 3000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (cond()) return true;
    await new Promise((r) => setTimeout(r, 10));
  }
  return false;
}
