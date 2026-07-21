import { describe, it, expect } from "vitest";
import { formatDate } from "./format";

describe("formatDate", () => {
  it("formats ISO to YYYY-MM-DD", () => {
    expect(formatDate("2026-07-21T09:30:00Z")).toBe("2026-07-21");
  });
  it("returns input on empty/invalid", () => {
    expect(formatDate("")).toBe("");
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});
