import { FileTextIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ErrorState";
import { useIncident } from "@/hooks/useIncident";
import { useRegenerateRootCause } from "@/hooks/useRegenerateRootCause";
import { severityColorVar, severityFor } from "@/lib/severity";

import { ConfidenceBadge } from "./ConfidenceBadge";
import { Evidence } from "./Evidence";

interface IncidentDetailPanelProps {
  incidentId: string;
  onClose: () => void;
}

export function IncidentDetailPanel({ incidentId, onClose }: IncidentDetailPanelProps) {
  const { data: incident, isPending, isError, error, refetch } = useIncident(incidentId);
  const regenerate = useRegenerateRootCause(incidentId);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex flex-col">
          <span className="text-xs font-medium text-muted-foreground">Incident</span>
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
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">Root cause</span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={regenerate.isPending}
                  onClick={() => regenerate.mutate()}
                >
                  <RefreshCwIcon className={regenerate.isPending ? "size-3.5 animate-spin" : "size-3.5"} />
                  {incident.root_cause_status === "ready" ? "Regenerate" : "Generate now"}
                </Button>
              </div>

              {regenerate.isError ? (
                <p className="text-xs text-destructive">
                  Couldn't regenerate the narrative —{" "}
                  {regenerate.error instanceof Error ? regenerate.error.message : "try again."}
                </p>
              ) : null}

              {incident.root_cause_status === "pending" ? (
                <PendingRootCause justRegenerated={regenerate.isSuccess} />
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

                  <Evidence evidence={incident.root_cause_evidence} />
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

function PendingRootCause({ justRegenerated }: { justRegenerated: boolean }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-dashed border-border px-3 py-3">
      <div className="flex items-center gap-2">
        <span className="size-1.5 animate-pulse rounded-full bg-severity-warning" />
        <span className="text-xs font-medium text-foreground">
          {justRegenerated ? "Regenerating narrative…" : "Narrative pending…"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Culprit hasn't finished analyzing this incident yet. This isn't an error — the
        root-cause job runs asynchronously and usually finishes within a few seconds.
      </p>
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
