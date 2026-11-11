// Derived from api-types.generated.ts (openapi-typescript, run via `npm
// run generate-types` — see package.json and justfile's `generate-types`
// recipe), which is itself generated from api/app/incidents/schemas.py's
// actual Pydantic models. This file used to hand-declare these shapes by
// hand as a second, driftable copy of that contract; now there's exactly
// one source of truth (the Python schemas) and this file just names the
// pieces the rest of the app imports.

import type { components } from "@/lib/api-types.generated";

export type IncidentSummary = components["schemas"]["IncidentSummary"];
export type IncidentDetail = components["schemas"]["IncidentDetail"];
export type AnomalyOut = components["schemas"]["AnomalyOut"];
export type CitedEvidenceOut = components["schemas"]["CitedEvidenceOut"];
export type PaginatedIncidents = components["schemas"]["PaginatedIncidents"];

export type IncidentStatus = IncidentSummary["status"];
export type RootCauseStatus = IncidentSummary["root_cause_status"];
export type Confidence = NonNullable<IncidentSummary["root_cause_confidence"]>;

// Phase 14/19: ingest keys and topology suggestions — served under
// /model since Phase 30, which removed the /services alias and every
// Service* shape with it.
export type TopologySuggestionOut = components["schemas"]["TopologySuggestionOut"];
export type TopologySuggestionsOut = components["schemas"]["TopologySuggestionsOut"];
export type TopologyEdgeRef = components["schemas"]["TopologyEdgeRef"];
export type KeyOut = components["schemas"]["KeyOut"];
export type KeyCreateResponse = components["schemas"]["KeyCreateResponse"];

// Phase 27: the system model — the only shapes that carry a component's
// kind or a connection's kind and criticality at all.
export type ComponentOut = components["schemas"]["ComponentOut"];
export type ComponentsOut = components["schemas"]["ComponentsOut"];
export type ComponentCreate = components["schemas"]["ComponentCreate"];
export type ComponentCreateResponse = components["schemas"]["ComponentCreateResponse"];
export type ComponentPatch = components["schemas"]["ComponentPatch"];
export type ConnectionOut = components["schemas"]["ConnectionOut"];
export type ConnectionsOut = components["schemas"]["ConnectionsOut"];
export type ConnectionCreate = components["schemas"]["ConnectionCreate"];
export type ConnectionPatch = components["schemas"]["ConnectionPatch"];
export type ComponentKind = ComponentOut["kind"];
export type ConnectionKind = ConnectionOut["kind"];
export type Criticality = ConnectionOut["criticality"];
export type GraphOut = components["schemas"]["GraphOut"];

// Phase 16: multi-user auth.
export type UserOut = components["schemas"]["UserOut"];
export type UsersOut = components["schemas"]["UsersOut"];
export type LoginResponse = components["schemas"]["LoginResponse"];
export type UserRole = UserOut["role"];

// Phase 18: postmortem write path.
export type PostmortemOut = components["schemas"]["PostmortemOut"];
export type PaginatedPostmortems = components["schemas"]["PaginatedPostmortems"];
export type PostmortemCreate = components["schemas"]["PostmortemCreate"];
export type PostmortemPatch = components["schemas"]["PostmortemPatch"];
export type EmbeddingStatus = PostmortemOut["embedding_status"];

// Phase 32 part 2: investigations, from `culprit diagnose`.
export type InvestigationSummary = components["schemas"]["InvestigationSummary"];
export type InvestigationList = components["schemas"]["InvestigationList"];
export type InvestigationTree = components["schemas"]["InvestigationTree"];
export type TreeEdge = components["schemas"]["TreeEdge"];
export type InvestigationReading = components["schemas"]["InvestigationReading"];
export type Reading = components["schemas"]["Reading"];
export type Hypothesis = components["schemas"]["Hypothesis"];
export type ConfidenceRubric = components["schemas"]["ConfidenceRubric"];
export type Symptom = components["schemas"]["Symptom"];
export type Diagnosis = components["schemas"]["Diagnosis"];

// Phase 33 part 3: agents, their pairing, allowances and tasks.
export type AgentSummary = components["schemas"]["AgentSummary"];
export type AgentList = components["schemas"]["AgentList"];
export type Allowance = components["schemas"]["Allowance"];
export type PairingCodeCreated = components["schemas"]["PairingCodeCreated"];
export type TaskCreate = components["schemas"]["TaskCreate"];
export type TaskCreated = components["schemas"]["TaskCreated"];
export type TaskView = components["schemas"]["TaskView"];

// Phase 34 part 2: verifications, and the outcomes they make.
export type Verification = components["schemas"]["Verification"];
export type VerificationVerdict = Verification["verdict"];
export type Change = components["schemas"]["Change"];
export type StoredVerification = components["schemas"]["StoredVerification"];
export type VerificationList = components["schemas"]["VerificationList"];
export type Accuracy = components["schemas"]["Accuracy"];
