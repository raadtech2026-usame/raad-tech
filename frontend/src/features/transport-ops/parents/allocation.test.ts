import { describe, expect, it } from "vitest";
import { allocateProRata, fromCents, toCents } from "./allocation";

describe("allocateProRata (mirrors the server's ADR-0047 §3 rule)", () => {
  const lines = [
    { lineId: "a", balanceDue: "33.34" },
    { lineId: "b", balanceDue: "33.33" },
    { lineId: "c", balanceDue: "33.33" },
  ];

  it("sums exactly to the payment and never exceeds a balance", () => {
    for (const total of ["0.01", "1.00", "10.00", "50.00", "99.99", "100.00"]) {
      const split = allocateProRata(total, lines)!;
      const sum = [...split.values()].reduce((acc, value) => acc + toCents(value), 0);
      expect(sum).toBe(toCents(total));
      for (const line of lines) {
        expect(toCents(split.get(line.lineId) ?? "0")).toBeLessThanOrEqual(toCents(line.balanceDue));
      }
    }
  });

  it("matches the server's split for an even family payment", () => {
    const split = allocateProRata("30.00", [
      { lineId: "mohamed", balanceDue: "40.00" },
      { lineId: "aisha", balanceDue: "40.00" },
    ]);
    expect(Object.fromEntries(split!)).toEqual({ mohamed: "15.00", aisha: "15.00" });
  });

  it("skips students who owe nothing and refuses overpayment or zero", () => {
    expect(Object.fromEntries(allocateProRata("10.00", [
      { lineId: "paid", balanceDue: "0.00" },
      { lineId: "owes", balanceDue: "40.00" },
    ])!)).toEqual({ owes: "10.00" });
    expect(allocateProRata("40.01", [{ lineId: "a", balanceDue: "40.00" }])).toBeNull();
    expect(allocateProRata("0.00", [{ lineId: "a", balanceDue: "40.00" }])).toBeNull();
  });

  it("converts cents without floating-point drift", () => {
    expect(toCents("12.10")).toBe(1210);
    expect(toCents("7")).toBe(700);
    expect(fromCents(1210)).toBe("12.10");
    expect(fromCents(5)).toBe("0.05");
  });
});
