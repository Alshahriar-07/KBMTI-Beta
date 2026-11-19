export function formatPrice(
  value: number | null | undefined,
  digits = 2,
  fallback = "—",
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatNumber(value: number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function formatPercent(
  value: number | null | undefined,
  digits = 2,
  fallback = "—",
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return fallback;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatSigned(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${formatPrice(value, digits)}`;
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value <= 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const scaled = value / 1024 ** exponent;
  return `${scaled.toFixed(scaled >= 100 ? 0 : 1)} ${units[exponent]}`;
}

/**
 * Timestamps are broker-server epoch seconds. We display them in UTC and label
 * them as broker time rather than claiming they are true UTC.
 */
export function formatBrokerTime(
  iso: string | null | undefined,
  withSeconds = false,
): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = date.toISOString().split("T");
  if (parts.length !== 2) return "—";
  const time = withSeconds ? parts[1].slice(0, 8) : parts[1].slice(0, 5);
  return `${parts[0]} ${time} UTC`;
}

export function formatClock(value: Date): string {
  return value.toLocaleTimeString("en-US", { hour12: false });
}

/** Broker-server clock, time only. Used in dense toolbars where the date is implied. */
export function formatTimeOnly(iso: string | null | undefined, withSeconds = true): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toISOString().split("T")[1]?.slice(0, withSeconds ? 8 : 5) ?? "—";
}

/** Compact age of a timestamp, for feed freshness next to a live clock. */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 1) return "now";
  if (total < 60) return `${total}s ago`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m ago`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

export function truncate(value: string, max = 120): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}
