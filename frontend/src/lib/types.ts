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
export type KeyOut = components["schemas"]["KeyOut"];
export type KeyCreateResponse = components["schemas"]["KeyCreateResponse"];
