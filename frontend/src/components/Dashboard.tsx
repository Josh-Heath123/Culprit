import { SearchIcon } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CommandPalette } from "@/components/command-palette/CommandPalette";
import { EmptyState } from "@/components/EmptyState";
import { IncidentDetailPanel } from "@/components/incident-detail/IncidentDetailPanel";
import { Page } from "@/components/layout/Page";
import { Timeline } from "@/components/timeline/Timeline";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorPanel } from "@/components/ui/states";
import { useIncidents } from "@/hooks/useIncidents";

/** The earlier incident-correlation engine's record (Phase 32 part 2:
 * read-only history). Selection lives in the URL — "/incidents" and
 * "/incidents/:incidentId" both render this — so an incident is
 * deep-linkable and back/forward move between the timeline and it. */
export function Dashboard() {
  const { incidentId } = useParams<{ incidentId?: string }>();
  const selectedIncidentId = incidentId ?? null;
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { incidents, total, isPending, isError, error, refetch } = useIncidents();

  return (
    <Page
      eyebrow="History"
      title="Incidents"
      description={
        <>
          {total} incident{total === 1 ? "" : "s"} from the earlier correlation engine, kept read-only. New
          diagnoses are{" "}
          <Link to="/investigations" className="text-brand underline-offset-2 hover:underline">
            investigations
          </Link>
          .
        </>
      }
      actions={
        incidents.length > 0 ? (
          <Button variant="outline" size="sm" onClick={() => setPaletteOpen(true)}>
            <SearchIcon aria-hidden />
            Jump to an incident
            <kbd className="ml-1 rounded-sm border border-line bg-surface-2 px-1 font-mono text-2xs text-fg-subtle">
              Ctrl K
            </kbd>
          </Button>
        ) : null
      }
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
        <Card className="min-w-0 flex-1 p-4" aria-label="Incident timeline">
          {isPending ? <TimelineSkeleton /> : null}
          {isError ? (
            <ErrorPanel
              title="Couldn't load incidents."
              message={error instanceof Error ? error.message : "The request failed."}
              onRetry={() => refetch()}
            />
          ) : null}
          {!isPending && !isError && incidents.length === 0 ? <EmptyState /> : null}
          {!isPending && !isError && incidents.length > 0 ? (
            // Below about 600 px the lanes cannot be read; the chart keeps
            // its width and scrolls inside its card instead of shrinking.
            <div className="h-96 overflow-x-auto lg:h-full lg:min-h-96">
              <div className="h-full min-w-xl">
                <Timeline
                  incidents={incidents}
                  selectedIncidentId={selectedIncidentId}
                  onSelectIncident={(id) => navigate(`/incidents/${id}`)}
                />
              </div>
            </div>
          ) : null}
        </Card>

        <Card className="flex min-h-64 flex-col overflow-hidden lg:w-96 lg:shrink-0">
          {selectedIncidentId ? (
            <IncidentDetailPanel incidentId={selectedIncidentId} onClose={() => navigate("/incidents")} />
          ) : incidents.length === 0 ? (
            <div className="flex flex-1 items-center justify-center px-6 py-10 text-center">
              <p className="text-sm text-fg-muted">An incident opens here when you choose one; there are none.</p>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 py-10 text-center">
              <p className="text-sm text-fg-muted">
                Choose an incident band on the timeline, or jump to one with{" "}
                <kbd className="font-mono text-xs text-fg">Ctrl K</kbd>.
              </p>
            </div>
          )}
        </Card>
      </div>

      <CommandPalette incidents={incidents} open={paletteOpen} onOpenChange={setPaletteOpen} />
    </Page>
  );
}

function TimelineSkeleton() {
  return (
    <div role="status" aria-busy="true" className="flex flex-col gap-3 py-2">
      <span className="sr-only">Loading incidents</span>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}
