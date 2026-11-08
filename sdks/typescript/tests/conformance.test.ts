// Shared spec test vectors. The Python SDK runs the same files.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { bucket, evaluate } from "../src/evaluation.js";
import { sha1Hex } from "../src/sha1.js";

interface EvalCase { name: string; flag: unknown; user: unknown; expected: unknown }
interface BucketCase { salt: string; value: unknown; bucket: number }

const load = <T>(name: string): T[] =>
  JSON.parse(
    readFileSync(fileURLToPath(new URL(`../../../spec/test-vectors/${name}`, import.meta.url)), "utf8"),
  ).cases;

describe("evaluation vectors", () => {
  test.each(load<EvalCase>("evaluation.json"))("$name", (c) => {
    expect(evaluate(c.flag, c.user)).toStrictEqual(c.expected);
  });
});

describe("bucketing vectors", () => {
  test.each(load<BucketCase>("bucketing.json"))("$salt : $value", (c) => {
    expect(bucket(c.salt, c.value)).toBe(c.bucket);
  });
});

test("sha1 known answers", () => {
  expect(sha1Hex("")).toBe("da39a3ee5e6b4b0d3255bfef95601890afd80709");
  expect(sha1Hex("abc")).toBe("a9993e364706816aba3e25717850c26c9cd0d89d");
  expect(sha1Hex("a".repeat(1000))).toBe("291e9a6c66994949b57ba5e650361e98fc36b1ba");
  expect(sha1Hex("héllo 🚀")).toBe("fa4896c1669ec5e952f54a3cd19330deef7582f8"); // multi-byte UTF-8 (python hashlib)
  // padding boundaries
  expect(sha1Hex("x".repeat(55))).toBe("cef734ba81a024479e09eb5a75b6ddae62e6abf1");
  expect(sha1Hex("x".repeat(56))).toBe("901305367c259952f4e7af8323f480d59f81335b");
  expect(sha1Hex("x".repeat(64))).toBe("bb2fa3ee7afb9f54c6dfb5d021f14b1ffe40c163");
});

test("raising a rollout only adds users", () => {
  const flag = (pct: number) => ({
    key: "f", on: true, variations: [true, false], off_variation: 1,
    fallthrough: { rollout: { variations: [{ variation: 0, weight: pct * 1000 }, { variation: 1, weight: 100000 - pct * 1000 }] } },
  });
  const on = (pct: number) =>
    new Set(Array.from({ length: 3000 }, (_, i) => `u${i}`).filter((id) => evaluate(flag(pct), { id }).value === true));
  let prev = new Set<string>();
  for (const pct of [0, 5, 10, 25, 50, 100]) {
    const cur = on(pct);
    for (const id of prev) expect(cur.has(id)).toBe(true);
    prev = cur;
  }
});
