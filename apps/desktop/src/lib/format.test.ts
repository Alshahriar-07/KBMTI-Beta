import { describe, expect, it } from "vitest";

import {
  formatBrokerTime,
  formatBytes,
  formatPercent,
  formatPrice,
  formatSigned,
} from "@/lib/format";

describe("format helpers", () => {
  it("formats prices with a fixed number of digits", () => {
    expect(formatPrice(64231.5, 2)).toBe("64,231.50");
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(Number.NaN)).toBe("—");
  });

  it("formats percentages with a sign", () => {
    expect(formatPercent(1.234)).toBe("+1.23%");
    expect(formatPercent(-0.5)).toBe("-0.50%");
    expect(formatPercent(null)).toBe("—");
  });

  it("formats signed values", () => {
    expect(formatSigned(12.5)).toBe("+12.50");
    expect(formatSigned(-12.5)).toBe("-12.50");
  });

  it("formats byte counts", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(0)).toBe("—");
  });

  it("renders broker timestamps as labelled UTC values", () => {
    expect(formatBrokerTime("2026-11-12T14:05:00+00:00")).toBe("2026-11-12 14:05 UTC");
    expect(formatBrokerTime("2026-11-12T14:05:09+00:00", true)).toBe("2026-11-12 14:05:09 UTC");
    expect(formatBrokerTime(null)).toBe("—");
  });
});
