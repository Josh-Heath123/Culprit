import { FileTextIcon, XIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ErrorState";
import { useIncident } from "@/hooks/useIncident";
import { severityColorVar, severityFor } from "@/lib/severity";

import { ConfidenceBadge } from "./ConfidenceBadge";
import { NarrativeCitations } from "./NarrativeCitations";

interface IncidentDetailPanelProps {
  incidentId: string;
  onClose: () => void;
}

export function IncidentDetailPanel({ incidentId, onClose }: IncidentDetailPanelProps) {
  const { data: incident, isPending, isError, error, refetch } = useIncident(incidentId);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex flex-col">
          <span className="text-xs font-medium text-muted-foreground">Incident · history</span>
          <span className="font-mono text-xs text-foreground">{incidentId}</span>
        </div>
        <div className="flex items-center gap-1">
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
          <ErrorState
            heading="Couldn't load this incident."
            message={error instanceof Error ? error.message : "Failed to load incident."}
            onRetry={() => refetch()}
          />
        ) : null}

        {incident ? (
          <div className="flex flex-col gap-4">
            <section className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Services</span>
              <div className="flex flex-wrap gap-1.5">
                {incident.services.map((service) => (
                  <Badge key={service} variant="outline">
                    {service}
                  </Badge>
                ))}
              </div>
            </section>

            <section className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Opened</span>
              <span className="font-mono text-xs text-foreground">
                {new Date(incident.opened_at).toLocaleString()}
              </span>
            </section>

            <Separator />

            <section className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">Root cause</span>
              {/* Phase 32 part 2: the correlation engine and the narrative
                  job are gone, and the incident tables are read-only. This
                  is the record of what that engine concluded, kept as
                  history; there is nothing left to regenerate it. */}
              <p className="text-[11px] text-muted-foreground">
                From the earlier incident-correlation engine, kept as history. New diagnoses are{" "}
                <Link to="/investigations" className="underline hover:text-foreground">
                  investigations
                </Link>
                .
              </p>

              {incident.root_cause_status === "pending" ? (
                <p className="text-xs text-muted-foreground">
                  No narrative was written for this incident before the engine was retired.
                </p>
              ) : (
                <div className="flex flex-col gap-3">
                  <p className="text-sm leading-snug text-foreground">
                    {incident.root_cause_hypothesis}
                  </p>

                  {incident.root_cause_confidence ? (
                    <div className="flex flex-col gap-1">
                      <ConfidenceBadge confidence={incident.root_cause_confidence} />
                      {incident.root_cause_confidence_reason ? (
                        <p className="text-xs text-muted-foreground">
                          {incident.root_cause_confidence_reason}
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  <NarrativeCitations evidence={incident.root_cause_evidence} />
                </div>
              )}
            </section>

            <Separator />

            <section className="flex flex-col gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                Anomalies ({incident.anomalies.length})
              </span>
              <ul className="flex flex-col gap-1.5">
                {incident.anomalies.map((anomaly) => {
                  const severity = severityFor(anomaly.score);
                  return (
                    <li
                      key={anomaly.id}
                      className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-1.5"
                    >
                      <div className="flex flex-col overflow-hidden">
                        <span className="truncate font-mono text-xs text-foreground">
                          {anomaly.metric_name}
                        </span>
                        <span className="font-mono text-[11px] text-muted-foreground">
                          {anomaly.service_name}
                        </span>
                      </div>
                      <span
                        className="shrink-0 font-mono text-xs font-medium"
                        style={{ color: severityColorVar(severity) }}
                      >
                        z={anomaly.score.toFixed(2)}
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
    <div className="flex flex-col gap-3">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}
