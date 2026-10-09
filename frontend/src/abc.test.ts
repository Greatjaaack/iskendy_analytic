import assert from "node:assert/strict";
import { test } from "node:test";
import { abcClassify } from "./abc.ts";

const classes = (values: number[]) => abcClassify(values, (v) => v).map((r) => r.cls).join("");

test("лидер с 85 % — класс A, а не B", () => {
  // сентябрь 2026: «Балык» 85 %; пятая позиция начинается на 95,7 % — уже C
  assert.equal(classes([85, 5.5, 3.2, 2, 1.5, 1, 0.8, 0.5, 0.5]), "ABBBCCCCC");
});

test("классика Парето: A до 80 %, B до 95 %", () => {
  assert.equal(classes([50, 25, 10, 8, 4, 3]), "AAABBC");
});

test("нулевые и отрицательные значения не участвуют, порядок по убыванию", () => {
  const rows = abcClassify([1, 0, -5, 3], (v) => v);
  assert.deepEqual(rows.map((r) => r.value), [3, 1]);
  assert.deepEqual(rows.map((r) => r.cum), [75, 100]);
});
