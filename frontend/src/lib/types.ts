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

// Phase 14: service registry.
export type ServiceOut = components["schemas"]["ServiceOut"];
export type ServicesOut = components["schemas"]["ServicesOut"];
export type ServiceCreate = components["schemas"]["ServiceCreate"];
export type ServiceCreateResponse = components["schemas"]["ServiceCreateResponse"];
export type ServicePatch = components["schemas"]["ServicePatch"];
export type TopologySuggestionOut = components["schemas"]["TopologySuggestionOut"];
export type TopologySuggestionsOut = components["schemas"]["TopologySuggestionsOut"];
export type TopologyEdgeRef = components["schemas"]["TopologyEdgeRef"];
export type KeyOut = components["schemas"]["KeyOut"];
export type KeyCreateResponse = components["schemas"]["KeyCreateResponse"];

// Phase 27: the system model. `/services*` above is a thin alias kept
// for one release (Phase 27 field 9) and removed in Phase 30 — new UI
// should read these, which are the only shapes that carry a component's
// kind or a connection's kind and criticality at all.
export type ComponentOut = components["schemas"]["ComponentOut"];
export type ComponentsOut = components["schemas"]["ComponentsOut"];
export type ComponentCreate = components["schemas"]["ComponentCreate"];
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
