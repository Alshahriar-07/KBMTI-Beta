export type ReadinessTone = "success" | "warning" | "danger" | "info" | "muted";

const SUCCESS = new Set(["READY", "AVAILABLE", "PASSED", "APPROVED"]);
const WARNING = new Set([
  "PENDING",
  "INITIALIZING",
  "CONFLICTING",
  "STALE",
  "LOW_CONFIDENCE",
  "NOT_EVALUATED",
  "NOT_CALCULATED",
]);
const DANGER = new Set(["FAILED", "REJECTED", "INVALID"]);

/** Shared status → badge mapping so the header and the panel never disagree. */
export function readinessTone(status: string): ReadinessTone {
  if (SUCCESS.has(status)) return "success";
  if (WARNING.has(status)) return "warning";
  if (DANGER.has(status)) return "danger";
  return "muted";
}
