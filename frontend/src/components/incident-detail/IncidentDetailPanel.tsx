import { FileTextIcon, HistoryIcon, XIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorPanel } from "@/components/ui/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useIncident } from "@/hooks/useIncident";
import { formatDateTime } from "@/lib/datetime";
import { severityFor, severityTextClass } from "@/lib/severity";

import { ConfidenceBadge } from "./ConfidenceBadge";
import { NarrativeCitations } from "./NarrativeCitations";

interface IncidentDetailPanelProps {
  incidentId: string;
  onClose: () => void;
}

/** One incident from the earlier correlation engine: a read-only record
 * (Phase 32 part 2). Labelled as history throughout, never presented as a
 * current diagnosis. */
export function IncidentDetailPanel({ incidentId, onClose }: IncidentDetailPanelProps) {
  const { data: incident, isPending, isError, error, refetch } = useIncident(incidentId);

  return (
    <div className="flex h-full flex-col" data-testid="incident-detail">
      <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="flex items-center gap-1 text-2xs font-semibold tracking-widest text-fg-subtle uppercase">
            <HistoryIcon aria-hidden className="size-3" />
            Incident · history
          </span>
          <h2 className="font-mono text-xs wrap-anywhere text-fg">{incidentId}</h2>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button asChild variant="ghost" size="sm">
            <Link to={`/incidents/${incidentId}/postmortem`}>
              <FileTextIcon className="size-3.5" />
              Write postmortem
            </Link>
          </Button>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close incident detail">
            <XIcon className="size-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isPending ? <DetailSkeleton /> : null}

        {isError ? (
          <ErrorPanel
            title="Couldn't load this incident."
            message={error instanceof Error ? error.message : "The request failed."}
            onRetry={() => refetch()}
          />
        ) : null}

        {incident ? (
          <div className="flex flex-col gap-5">
            <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-xs">
              <dt className="text-fg-subtle">Services</dt>
              <dd className="col-span-2 flex flex-wrap gap-1.5">
                {incident.services.map((service) => (
                  <Badge key={service} variant="outline">
                    {service}
                  </Badge>
                ))}
              </dd>
              <dt className="text-fg-subtle">Opened</dt>
              <dd className="col-span-2 text-fg">
                <time dateTime={incident.opened_at}>{formatDateTime(incident.opened_at)}</time>
              </dd>
            </dl>

            <section className="flex flex-col gap-2 border-t border-line pt-4" aria-labelledby="incident-cause">
              <h3 id="incident-cause" className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">
                The engine's conclusion
              </h3>
              {/* Phase 32 part 2: the correlation engine and the narrative
                  job are gone, and the incident tables are read-only. This
                  is the record of what that engine concluded, kept as
                  history; there is nothing left to regenerate it. */}
              <p className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-fg-muted">
                From the earlier incident-correlation engine, kept as history. New diagnoses are{" "}
                <Link to="/investigations" className="text-brand underline-offset-2 hover:underline">
                  investigations
                </Link>
                .
              </p>

              {incident.root_cause_status === "pending" ? (
                <p className="text-sm text-fg-muted">
                  No narrative was written for this incident before the engine was retired.
                </p>
              ) : (
                <div className="flex flex-col gap-3">
                  <p className="text-sm leading-relaxed text-fg">{incident.root_cause_hypothesis}</p>

                  {incident.root_cause_confidence ? (
                    <div className="flex flex-col gap-1">
                      <ConfidenceBadge confidence={incident.root_cause_confidence} />
                      {incident.root_cause_confidence_reason ? (
                        <p className="text-xs text-fg-muted">{incident.root_cause_confidence_reason}</p>
                      ) : null}
                    </div>
                  ) : null}

                  <NarrativeCitations evidence={incident.root_cause_evidence} />
                </div>
              )}
            </section>

            <section className="flex flex-col gap-2 border-t border-line pt-4" aria-labelledby="incident-anomalies">
              <h3 id="incident-anomalies" className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">
                Anomalies <span className="font-mono">{incident.anomalies.length}</span>
              </h3>
              <ul className="flex flex-col gap-1.5">
                {incident.anomalies.map((anomaly) => {
                  const severity = severityFor(anomaly.score);
                  return (
                    <li
                      key={anomaly.id}
                      className="flex items-center justify-between gap-2 rounded-md border border-line bg-surface-2 px-3 py-2"
                    >
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate font-mono text-xs text-fg">{anomaly.metric_name}</span>
                        <span className="font-mono text-2xs text-fg-muted">{anomaly.service_name}</span>
                      </div>
                      <span className={`shrink-0 font-mono text-xs font-medium ${severityTextClass(severity)}`}>
                        z={anomaly.score.toFixed(2)} <span className="text-2xs">{severity}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div role="status" aria-busy="true" className="flex flex-col gap-3">
      <span className="sr-only">Loading the incident</span>
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}
