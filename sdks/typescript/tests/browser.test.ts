import { afterEach, beforeEach, expect, test } from "vitest";
import { BrowserFlagClient } from "../src/browser.js";
import { FakeServer, waitFor } from "./fakeServer.js";

let server: FakeServer;
let client: BrowserFlagClient | undefined;
let bannerOn = true;

const detail = (value: unknown, idx: number) => ({ value, variation_index: idx, reason: { kind: "FALLTHROUGH" } });

beforeEach(async () => {
  bannerOn = true;
  server = await new FakeServer({}, 5).start();
  server.evaluate = (user) => ({
    banner: bannerOn ? detail(true, 0) : detail(false, 1),
    greeting: detail(`hi ${user.id}`, 0),
  });
});
afterEach(async () => {
  await client?.close();
  client = undefined;
  await server.stop();
});

const make = (opts = {}) =>
  new BrowserFlagClient("cli-test", { id: "alice" }, { baseUrl: server.url, backoff: () => 50, sendEvents: false, ...opts });

test("loads evaluated values for the user", async () => {
  client = make();
  expect(client.bool("banner", false)).toBe(false); // before load: default
  expect(await client.waitForInitialization(2000)).toBe(true);
  expect(client.bool("banner", false)).toBe(true);
  expect(client.string("greeting", "")).toBe("hi alice");
  expect(server.evaluateRequests[0]).toEqual({ id: "alice" });
});

test("re-evaluates when the server pings a change", async () => {
  client = make();
  await client.waitForInitialization();
  const changes: string[][] = [];
  client.onChange((k) => changes.push(k));
  bannerOn = false;
  server.envVersion = 6;
  server.send("change", { env_version: 6 });
  expect(await waitFor(() => client!.bool("banner", true) === false)).toBe(true);
  expect(changes).toEqual([["banner"]]);
});

test("identify switches user", async () => {
  client = make({ stream: false });
  await client.waitForInitialization();
  await client.identify({ id: "bob" });
  expect(client.string("greeting", "")).toBe("hi bob");
});

test("a slow response for an old user does not overwrite the new user", async () => {
  client = make({ stream: false });
  await client.waitForInitialization();
  server.evaluateDelayMs = 300;
  const slow = client.identify({ id: "slow" });
  server.evaluateDelayMs = 0;
  await client.identify({ id: "fast" });
  await slow;
  expect(client.string("greeting", "")).toBe("hi fast");
});

test("server unavailable: defaults, never throws", async () => {
  await server.stop();
  client = make();
  expect(await client.waitForInitialization(300)).toBe(false);
  expect(client.variationDetail("banner", false)).toMatchObject({ value: false, reason: { error_kind: "CLIENT_NOT_READY" } });
  server = await new FakeServer().start();
});

test("bootstrap values are served immediately", () => {
  client = make({ stream: false, bootstrap: { banner: detail(true, 0) } });
  expect(client.bool("banner", false)).toBe(true);
});
