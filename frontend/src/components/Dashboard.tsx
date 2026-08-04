import { useNavigate, useParams } from "react-router-dom";

import { CommandPalette } from "@/components/command-palette/CommandPalette";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { IncidentDetailPanel } from "@/components/incident-detail/IncidentDetailPanel";
import { Nav } from "@/components/layout/Nav";
import { Timeline } from "@/components/timeline/Timeline";
import { Skeleton } from "@/components/ui/skeleton";
import { useIncidents } from "@/hooks/useIncidents";

export function Dashboard() {
  // Selection lives in the URL (see routes/AppRoutes.tsx's "/" and
  // "/incidents/:incidentId" both rendering this component), not local
  // state — that's what makes an incident deep-linkable and what makes
  // browser back/forward move between the timeline and an open incident.
  const { incidentId } = useParams<{ incidentId?: string }>();
  const selectedIncidentId = incidentId ?? null;
  const navigate = useNavigate();
  const { incidents, total, isPending, isError, error, refetch } = useIncidents();

  return (
    <div className="flex h-screen flex-col">
      <Nav totalIncidents={total} />

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 border-r border-border p-4">
          {isPending ? <TimelineSkeleton /> : null}
          {isError ? (
            <ErrorState
              message={error instanceof Error ? error.message : "Unknown error"}
              onRetry={() => refetch()}
            />
          ) : null}
          {!isPending && !isError && incidents.length === 0 ? <EmptyState /> : null}
          {!isPending && !isError && incidents.length > 0 ? (
            <Timeline
              incidents={incidents}
              selectedIncidentId={selectedIncidentId}
              onSelectIncident={(id) => navigate(`/incidents/${id}`)}
            />
          ) : null}
        </main>

        <aside className="w-96 shrink-0">
          {selectedIncidentId ? (
            <IncidentDetailPanel incidentId={selectedIncidentId} onClose={() => navigate("/")} />
          ) : (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <p className="text-xs text-muted-foreground">
                Select an anomaly or incident band on the timeline, or press ⌘K to jump to one.
              </p>
            </div>
          )}
        </aside>
      </div>

      <CommandPalette incidents={incidents} />
    </div>
  );
}

function TimelineSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 py-2">
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}
