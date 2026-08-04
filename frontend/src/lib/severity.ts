// Pure — maps an anomaly's z-score to a severity bucket. Every anomaly
// reaching this app already crossed worker/app/anomaly/scorer.py's
// ANOMALY_THRESHOLD (3.0), so this only distinguishes "anomalous" from
// "very anomalous," not "anomalous" from "normal" — that decision
// already happened server-side, deterministically, before this ever
// existed as a row.

export type Severity = "warning" | "critical";

const CRITICAL_THRESHOLD = 6;

export function severityFor(score: number): Severity {
  return Math.abs(score) >= CRITICAL_THRESHOLD ? "critical" : "warning";
}

export function severityColorVar(severity: Severity): string {
  return severity === "critical" ? "var(--destructive)" : "var(--severity-warning)";
}

/** Mark radius scales mildly with magnitude so a more severe anomaly is
 * visibly larger, not just a different color — dense marks on the
 * timeline should read as data, not decoration. */
export function markRadiusFor(score: number): number {
  const clamped = Math.min(Math.abs(score), 12);
  return 3 + clamped * 0.4;
}
