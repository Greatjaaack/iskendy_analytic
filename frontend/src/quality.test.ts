import assert from "node:assert/strict";
import { test } from "node:test";
import { foodCostLevel, profitLevel } from "./quality.ts";

test("food cost 5 % — не «отлично», а нет оценки", () => {
  assert.equal(foodCostLevel(5.4), null); // с/с «Балыка» 3 % цены
  assert.equal(foodCostLevel(9.9), null);
});

test("food cost по порогам, когда с/с правдоподобна", () => {
  assert.equal(foodCostLevel(22), "good");
  assert.equal(foodCostLevel(28), "warn");
  assert.equal(foodCostLevel(35), "bad");
  assert.equal(foodCostLevel(null), null);
});

test("бэкенд счёл с/с ненадёжной — не красим даже правдоподобный процент", () => {
  assert.equal(foodCostLevel(22, false), null);
});

test("прибыль: плюс без полных данных не зелёный, убыток красный всегда", () => {
  assert.equal(profitLevel(3_552_021, true), null);
  assert.equal(profitLevel(3_552_021, false), "good");
  assert.equal(profitLevel(-120_000, true), "bad");
  assert.equal(profitLevel(-120_000, false), "bad");
});
