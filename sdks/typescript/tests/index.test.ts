import { expect, test } from "vitest";
import { VERSION } from "../src/index";

test("version", () => {
  expect(VERSION).toBeTruthy();
});
