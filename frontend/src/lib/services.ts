// Hardcoded, per the project's own scope rule (CLAUDE.md: "two to three
// services, hardcoded, not N services configurable") — the same rule
// Phase 2's demo services and Phase 5's correlation adjacency graph
// already follow. Lane order on the timeline matches this array.
export const SERVICES = ["order-service", "inventory-service", "payments-service"] as const;

export type ServiceName = (typeof SERVICES)[number];
