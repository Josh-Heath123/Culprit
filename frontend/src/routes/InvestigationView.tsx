import { ChevronLeftIcon } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { AppHeader } from "@/components/layout/AppHeader";
import { DiagnosisCard } from "@/components/investigation/Diagnosis";
import { FaultTree } from "@/components/investigation/FaultTree";
import { Hypotheses } from "@/components/investigation/Hypotheses";
import { ErrorPanel, LoadingInvestigation } from "@/components/investigation/States";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useInvestigationTree } from "@/hooks/useInvestigations";
import { ApiError } from "@/lib/api";
import type { InvestigationTree, Symptom } from "@/lib/types";

/** One investigation: the fault tree `culprit diagnose` established,
 * shown as it was stored. Nothing here computes a verdict, ranks a
 * hypothesis or opens a probe — the view renders what the walk decided
 * (DIAGNOSTIC_PLAN.md Phase 32, field 17: no control that opens or
 * extends an investigation until there is an agent to run it). */
export function InvestigationView() {
  const { investigationId = "" } = useParams();
  const { data, isPending, isError, error, refetch } = useInvestigationTree(investigationId);

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader
        trail={
          <span className="hidden truncate font-mono text-xs text-fg-subtle lg:block">{investigationId}</span>
        }
      />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-5 px-4 py-6 sm:px-6 sm:py-8">
        <Link
          to="/investigations"
          className="flex items-center gap-1 self-start rounded-sm text-xs text-fg-muted transition-colors duration-150 hover:text-fg"
        >
          <ChevronLeftIcon aria-hidden className="size-3.5" />
          All investigations
        </Link>
        {isPending ? <LoadingInvestigation /> : null}
        {isError ? (
          error instanceof ApiError && error.status === 404 ? (
            // A retry cannot make a missing investigation exist.
            <ErrorPanel
              title="No investigation with this id is stored."
              message={`${investigationId} — investigations are only ever added by culprit diagnose, never renamed.`}
            />
          ) : (
            <ErrorPanel
              title="Couldn't load this investigation."
              message={error instanceof Error ? error.message : "The request failed."}
              onRetry={() => refetch()}
            />
          )
        ) : null}
        {data ? <InvestigationBody investigation={data} /> : null}
      </main>
    </div>
  );
}

function InvestigationBody({ investigation }: { investigation: InvestigationTree }) {
  const { diagnosis, symptom } = investigation;
  return (
    <>
      <div className="flex flex-col gap-2">
        <h1 className="font-mono text-lg font-semibold wrap-anywhere text-fg sm:text-2xl">{symptom.subject}</h1>
        {symptom.description ? <p className="text-sm leading-relaxed text-fg-muted">{symptom.description}</p> : null}
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-5 lg:col-span-2">
          <DiagnosisCard diagnosis={diagnosis} unexplored={investigation.hypotheses.unexplored} />
          <FaultTree
            edges={investigation.fault_tree}
            symptom={symptom.subject}
            boundary={diagnosis?.root_subject ?? null}
            complete={diagnosis?.complete ?? false}
          />
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <SymptomCard investigation={investigation} />
          <Hypotheses groups={investigation.hypotheses} />
        </div>
      </div>
    </>
  );
}

/** Glass: the one summary layer on the page, beside the dense data. */
function SymptomCard({ investigation }: { investigation: InvestigationTree }) {
  const { symptom } = investigation;
  return (
    <Card surface="glass" aria-labelledby="symptom-heading">
      <CardHeader id="symptom-heading" title="Symptom" />
      <CardBody className="flex flex-col gap-4">
        <Attestation symptom={symptom} />
        <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-xs">
          <dt className="text-fg-subtle">Kind</dt>
          <dd className="col-span-2 font-mono text-fg">{symptom.kind}</dd>
          <dt className="text-fg-subtle">Environment</dt>
          <dd className="col-span-2 font-mono wrap-anywhere text-fg">{investigation.environment}</dd>
          <dt className="text-fg-subtle">Opened</dt>
          <dd className="col-span-2 text-fg">
            <time dateTime={investigation.opened_at}>{new Date(investigation.opened_at).toLocaleString()}</time>
          </dd>
          <dt className="text-fg-subtle">Investigation</dt>
          <dd className="col-span-2 font-mono wrap-anywhere text-fg-muted">{investigation.id}</dd>
        </dl>
      </CardBody>
    </Card>
  );
}

function Attestation({ symptom }: { symptom: Symptom }) {
  const { attestation } = symptom;
  return (
    <div className="flex flex-col gap-1.5" data-testid="attestation">
      <Badge variant={attestation.kind === "reproduced" ? "primary" : "outline"} className="self-start">
        {attestation.kind}
      </Badge>
      <p className="text-xs leading-relaxed text-fg-muted">
        {attestation.kind === "reproduced"
          ? `The walk reproduced it read-only: reading ${attestation.reading}.`
          : `Reported by ${attestation.reported_by}. Not reproduced — a probe never replays a write.`}
      </p>
    </div>
  );
}
