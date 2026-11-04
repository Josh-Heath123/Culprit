import { Link } from "react-router-dom";

import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useComponents } from "@/hooks/useModel";

/** Built from the actually-registered component list (GET
 * /model/components since Phase 30; GET /services before it, and a
 * hardcoded three-name array before Phase 14), matching the terse,
 * specific voice of the LLM narratives (Section 3): state exactly what
 * was checked and found nothing, not that something is broken.
 * Deliberately doesn't claim a time window ("in the last 4 hours") this
 * endpoint doesn't actually enforce — GET /incidents returns every
 * open-ended incident_candidate, not a windowed slice, so the copy stays
 * honest about what "empty" here actually means. */
export function EmptyState() {
  const { data: me } = useCurrentUser();
  const isAdmin = me?.role === "admin";
  const { components } = useComponents({ enabled: isAdmin });
  const active = components.filter((c) => !c.disabled);

  // A member cannot read the component registry (/model is admin-only),
  // so "no services registered" would be a guess, and the link would
  // lead to a page they cannot use.
  if (!isAdmin) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
        <p className="text-sm text-foreground">No anomalies detected.</p>
        <p className="text-xs text-muted-foreground">
          Culprit is watching. Incidents appear here as soon as one opens.
        </p>
      </div>
    );
  }

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
