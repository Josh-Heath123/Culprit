// Hand-synced mirror of shared/culprit_shared/services.py's SERVICES —
// hardcoded, per the project's own scope rule (CLAUDE.md: "two to three
// services, hardcoded, not N services configurable"), so this is a
// small enough, low-churn enough list that a generated-from-Python build
// step isn't worth it (unlike frontend/src/lib/types.ts, which is
// generated — see api-types.generated.ts). If the Python list ever
// changes, update this one too. Lane order on the timeline matches this array.
export const SERVICES = ["order-service", "inventory-service", "payments-service"] as const;

export type ServiceName = (typeof SERVICES)[number];
