import { afterEach, beforeEach, expect, test } from "vitest";
import { FlagClient } from "../src/server.js";
import { boolFlag, FakeServer, waitFor } from "./fakeServer.js";

let server: FakeServer;
let client: FlagClient | undefined;
const user = { id: "u" };

beforeEach(async () => {
  server = await new FakeServer({ f: boolFlag() }).start();
});
afterEach(async () => {
  await client?.close();
  client = undefined;
  await server.stop();
});

const make = (opts = {}) =>
  FlagClient.init("srv-test", { baseUrl: server.url, backoff: () => 50, eventsFlushIntervalMs: 60_000, ...opts });

test("initializes from the stream and evaluates locally", async () => {
  client = await make();
  expect(client.isReady()).toBe(true);
  expect(client.bool("f", user, false)).toBe(true);
});

test("applies patches and notifies listeners", async () => {
  client = await make();
  const changed: string[] = [];
  client.onChange((k) => changed.push(k));
  server.patch("f", boolFlag("f", { on: false, version: 2 }));
  expect(await waitFor(() => client!.bool("f", user, true) === false)).toBe(true);
  expect(changed).toEqual(["f"]);
});

test("ignores stale patches", async () => {
  client = await make();
  server.send("patch", { env_version: 1, key: "f", flag: boolFlag("f", { on: false }) });
  server.patch("g", boolFlag("g"));
  expect(await waitFor(() => client!.bool("g", user, false))).toBe(true);
  expect(client.bool("f", user, false)).toBe(true);
});

test("re-syncs after a version gap", async () => {
  client = await make();
  server.flags.h = boolFlag("h");
  server.patch("g", boolFlag("g"), 3);
  expect(await waitFor(() => client!.bool("h", user, false))).toBe(true);
  expect(server.snapshotRequests).toBe(1);
});

test("deleted flag returns the default", async () => {
  client = await make();
  server.patch("f", null);
  expect(await waitFor(() => client!.variationDetail("f", user, "d").reason.kind === "ERROR")).toBe(true);
  expect(client.variationDetail("f", user, "d")).toMatchObject({ value: "d", reason: { error_kind: "FLAG_NOT_FOUND" } });
});

test("server down at startup: defaults, no throw, bounded wait", async () => {
  await server.stop();
  const started = Date.now();
  client = await FlagClient.init("srv-x", { baseUrl: server.url, initTimeoutMs: 300, sendEvents: false, backoff: () => 50 });
  expect(Date.now() - started).toBeLessThan(1500);
  expect(client.isReady()).toBe(false);
  expect(client.variationDetail("f", user, "fallback")).toMatchObject({
    value: "fallback", reason: { error_kind: "CLIENT_NOT_READY" },
  });
  server = await new FakeServer().start(); // for afterEach
});

test("keeps last known flags while the server is down, then reconnects", async () => {
  client = await make({ sendEvents: false });
  const port = server.port;
  await server.stop();
  await new Promise((r) => setTimeout(r, 200));
  expect(client.bool("f", user, false)).toBe(true);
  server = await new FakeServer({ f: boolFlag("f", { on: false }) }, 7).start(port);
  expect(await waitFor(() => client!.bool("f", user, true) === false, 5000)).toBe(true);
});

test("type mismatch, unknown flag, and invalid user return the default", async () => {
  client = await make();
  expect(client.string("f", user, "x")).toBe("x");
  expect(client.number("f", user, 3)).toBe(3);
  expect(client.bool("missing", user, false)).toBe(false);
  expect(client.bool("f", null as any, false)).toBe(false);
  expect(client.bool("f", {} as any, false)).toBe(false);
});

test("a malformed flag from the server returns the default", async () => {
  server.flags.bad = { ...boolFlag("bad"), fallthrough: { variation: 9 } };
  client = await make();
  expect(client.variationDetail("bad", user, false)).toMatchObject({
    value: false, reason: { error_kind: "MALFORMED_FLAG" },
  });
});

test("a throwing listener does not break updates", async () => {
  client = await make();
  client.onChange(() => { throw new Error("listener bug"); });
  server.patch("f", boolFlag("f", { on: false }));
  server.patch("g", boolFlag("g"));
  expect(await waitFor(() => client!.bool("g", user, false))).toBe(true);
});

test("experiment exposures are sent once per user and variation", async () => {
  server.flags.exp = { ...boolFlag("exp"), fallthrough: { rollout: { kind: "experiment", variations: [{ variation: 0, weight: 100000 }] } } };
  client = await make();
  for (let i = 0; i < 5; i++) client.bool("exp", { id: "u1" }, false);
  client.bool("exp", { id: "u2" }, false);
  client.bool("f", { id: "u1" }, false);
  client.track({ id: "u1" }, "purchase", 20);
  await client.flush();
  expect(server.events.filter((e) => e.kind === "exposure").map((e) => e.user_id).sort()).toEqual(["u1", "u2"]);
  expect(server.events.filter((e) => e.kind === "custom")).toHaveLength(1);
});

test("a full event buffer drops instead of growing", async () => {
  client = await make({ eventsCapacity: 10 });
  for (let i = 0; i < 1000; i++) client.track({ id: `u${i}` }, "m");
  expect(client.droppedEvents).toBe(990);
});

test("polling mode", async () => {
  client = await make({ stream: false, pollIntervalMs: 50 });
  expect(client.bool("f", user, false)).toBe(true);
  server.flags.f = boolFlag("f", { on: false });
  expect(await waitFor(() => client!.bool("f", user, true) === false)).toBe(true);
});

test("offline bootstrap and idempotent close", async () => {
  client = new FlagClient("x", { offline: true, bootstrap: { env_version: 1, flags: { f: boolFlag() as any } } });
  expect(client.bool("f", user, false)).toBe(true);
  await client.close();
  await client.close();
});
