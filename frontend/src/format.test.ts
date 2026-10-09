import assert from "node:assert/strict";
import { test } from "node:test";
import { shiftISO } from "./format.ts";

test("сдвиг даты через границы месяца, года и високосный день", () => {
  assert.equal(shiftISO("2026-10-31", 1), "2026-11-01");
  assert.equal(shiftISO("2026-01-01", -1), "2025-12-31");
  assert.equal(shiftISO("2024-02-28", 1), "2024-02-29");
  assert.equal(shiftISO("2026-03-29", -1), "2026-03-28"); // переход на летнее время в Европе
  assert.equal(shiftISO("2026-10-09", -7), "2026-10-02");
});
