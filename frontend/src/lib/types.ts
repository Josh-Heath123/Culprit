// Mirrors api/app/incidents/schemas.py exactly — keep these two in sync
// by hand; Phase 7 is intentionally minimal and doesn't generate this.

export type IncidentStatus = "open" | "investigating" | "resolved";
export type RootCauseStatus = "pending" | "ready";
export type Confidence = "High" | "Medium" | "Low";

export interface AnomalyOut {
  id: string;
  service_name: string;
  metric_name: string;
  score: number;
  detected_at: string;
}

export interface CitedEvidenceOut {
  postmortem_id: string | null;
  postmortem_title: string;
  passage: string;
}

export interface IncidentSummary {
  id: string;
  status: IncidentStatus;
  opened_at: string;
  closed_at: string | null;
  last_anomaly_at: string;
  services: string[];
  anomalies: AnomalyOut[];
  root_cause_status: RootCauseStatus;
  root_cause_hypothesis: string | null;
  root_cause_confidence: Confidence | null;
}

export interface IncidentDetail extends IncidentSummary {
  root_cause_confidence_reason: string | null;
  root_cause_evidence: CitedEvidenceOut[];
  root_cause_generated_at: string | null;
}

export interface PaginatedIncidents {
  items: IncidentSummary[];
  limit: number;
  offset: number;
  total: number;
}
