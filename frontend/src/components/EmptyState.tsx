import { Link } from "react-router-dom";

import { useServices } from "@/hooks/useServices";

/** Built from the actually-registered service list (Phase 14: GET
 * /services, not a hardcoded three-name array), matching the terse,
 * specific voice of the LLM narratives (Section 3): state exactly what
 * was checked and found nothing, not that something is broken.
 * Deliberately doesn't claim a time window ("in the last 4 hours") this
 * endpoint doesn't actually enforce — GET /incidents returns every
 * open-ended incident_candidate, not a windowed slice, so the copy stays
 * honest about what "empty" here actually means. */
export function EmptyState() {
  const { services } = useServices();
  const active = services.filter((s) => !s.disabled);

  if (active.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="text-sm text-foreground">No services registered yet.</p>
        <p className="text-xs text-muted-foreground">
          <Link to="/settings/services" className="underline underline-offset-2">
            Register a service
          </Link>{" "}
          and point it at Culprit to start seeing anomalies here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
      <p className="text-sm text-foreground">
        No anomalies detected across {active.map((s) => s.display_name ?? s.name).join(", ")}.
      </p>
      <p className="text-xs text-muted-foreground">
        Culprit is watching. Trigger a fault or wait for real traffic to see something here.
      </p>
    </div>
  );
}
