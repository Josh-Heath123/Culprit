import { SERVICES } from "@/lib/services";

/** Built from the actual configured service list, not a generic "No
 * data" string — matches the terse, specific voice of the LLM
 * narratives (Section 3): state exactly what was checked and found
 * nothing, not that something is broken. Deliberately doesn't claim a
 * time window ("in the last 4 hours") this endpoint doesn't actually
 * enforce — GET /incidents returns every open-ended incident_candidate,
 * not a windowed slice, so the copy stays honest about what "empty"
 * here actually means. */
export function EmptyState() {
  const services = SERVICES.join(", ");
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
      <p className="text-sm text-foreground">
        No anomalies detected across {services}.
      </p>
      <p className="text-xs text-muted-foreground">
        Culprit is watching. Trigger a fault or wait for real traffic to see something here.
      </p>
    </div>
  );
}
