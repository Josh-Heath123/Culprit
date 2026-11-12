/** Hypothesis kinds as words: the label reads as English, and the exact
 * kind is shown beneath it in monospace. The source is
 * shared/tests/investigation_conformance.json's hypothesis_labels, which the
 * Go binary copies too; this build cannot read that file at run time, so
 * lib/hypotheses.test.ts fails unless this copy equals it exactly — a new
 * kind cannot ship unlabelled, and a label cannot drift from the CLI's. */
export const HYPOTHESIS_LABELS: Readonly<Record<string, string>> = {
  component_fails: "Component fails",
  connection_unreachable: "Connection unreachable",
  database_unreachable: "Database unreachable",
  tls_invalid: "TLS certificate invalid",
  auth_audience_mismatch: "Auth audience mismatch",
  auth_rejected: "Auth rejected",
  contract_mismatch: "Contract mismatch",
  config_missing: "Config missing",
  latency_budget_exceeded: "Latency budget exceeded",
};

/** The label, or — for a kind this build does not know, stored by a newer
 * binary — the kind itself with its underscores as spaces, never blank. */
export function hypothesisLabel(kind: string): string {
  const label = HYPOTHESIS_LABELS[kind];
  if (label) return label;
  const words = kind.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
