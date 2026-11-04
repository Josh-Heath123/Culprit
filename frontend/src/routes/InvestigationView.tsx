import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { Evidence } from "@/components/investigation/Evidence";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useInvestigationTree } from "@/hooks/useInvestigations";
import type { ConfidenceRubric, Hypothesis, InvestigationTree, Symptom, TreeEdge } from "@/lib/types";

/** One investigation: the fault tree `culprit diagnose` established,
 * shown as it was stored. Nothing here computes a verdict, ranks a
 * hypothesis or opens a probe — the view renders what the walk decided
 * (DIAGNOSTIC_PLAN.md Phase 32, field 17: no control that opens or
 * extends an investigation until there is an agent to run it). */
export function InvestigationView() {
  const { investigationId = "" } = useParams();
  const { data, isPending, isError, error, refetch } = useInvestigationTree(investigationId);

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <Link to="/investigations" className="text-xs text-muted-foreground hover:text-foreground">
          / Investigations
        </Link>
        <span className="truncate font-mono text-xs text-muted-foreground">/ {investigationId}</span>
      </header>

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 overflow-y-auto p-6">
        {isPending ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : null}
        {isError ? (
          <ErrorState
            heading="Couldn't load this investigation."
            message={error instanceof Error ? error.message : "Failed to load investigation."}
            onRetry={() => refetch()}
          />
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
      <section className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">Symptom</span>
        <span className="font-mono text-sm text-foreground">{symptom.subject}</span>
        {symptom.description ? <p className="text-xs text-foreground">{symptom.description}</p> : null}
        <AttestationLine symptom={symptom} />
        <span className="text-[11px] text-muted-foreground/70">
          {investigation.environment} · opened {new Date(investigation.opened_at).toLocaleString()}
        </span>
      </section>

      <Separator />

      <section className="flex flex-col gap-2" data-testid="diagnosis">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Diagnosis</span>
          {diagnosis ? (
            <Badge variant={diagnosis.complete ? "primary" : "warning"}>
              {diagnosis.complete ? "complete" : "partial"}
            </Badge>
          ) : null}
        </div>
        {diagnosis ? (
          <>
            <p className="text-sm leading-snug text-foreground">{diagnosis.statement}</p>
            {diagnosis.remediation ? (
              <p className="text-xs text-muted-foreground">Remediation: {diagnosis.remediation}</p>
            ) : null}
            <Rubric rubric={diagnosis.confidence} />
          </>
        ) : (
          <p className="text-xs text-muted-foreground">The walk reached no diagnosis.</p>
        )}
      </section>

      <Separator />

      <section className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">Fault tree</span>
        <FaultTree
          edges={investigation.fault_tree}
          symptom={symptom.subject}
          root={diagnosis?.root_subject ?? null}
        />
      </section>

      <Separator />

      <Hypotheses groups={investigation.hypotheses} />
    </>
  );
}

function AttestationLine({ symptom }: { symptom: Symptom }) {
  const { attestation } = symptom;
  return (
    <div className="flex items-center gap-1.5 text-xs" data-testid="attestation">
      <Badge variant={attestation.kind === "reproduced" ? "primary" : "outline"}>{attestation.kind}</Badge>
      <span className="text-muted-foreground">
        {attestation.kind === "reproduced"
          ? `the walk reproduced it — reading ${attestation.reading}`
          : `reported by ${attestation.reported_by}; the walk did not reproduce it itself`}
      </span>
    </div>
  );
}

const CRITERIA = ["reproduced", "discriminated", "counterfactual", "verified"] as const;

/** §2.9's rubric as four booleans, each with the reason it holds or not.
 * Never collapsed into one number: which criterion is missing is the
 * information. */
function Rubric({ rubric }: { rubric: ConfidenceRubric }) {
  return (
    <ul className="flex flex-col gap-1" data-testid="rubric">
      {CRITERIA.map((name) => {
        const criterion = rubric[name];
        return (
          <li key={name} className="flex items-baseline gap-2 text-xs" data-criterion={name} data-holds={criterion.holds}>
            <span className={criterion.holds ? "font-mono text-primary" : "font-mono text-muted-foreground"}>
              {criterion.holds ? "✓" : "✗"}
            </span>
            <span className="w-28 shrink-0 font-medium text-foreground">{name}</span>
            <span className="text-muted-foreground">{criterion.reason}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** The edges as a tree from the symptom down. An edge whose parent is not
 * reachable from the symptom is still shown, as a start of its own — the
 * view must never drop an established edge because it does not fit a
 * shape it expected. */
function FaultTree({ edges, symptom, root }: { edges: TreeEdge[]; symptom: string; root: string | null }) {
  if (edges.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No edge was established{root ? ` — the root (${root}) was reached without one` : ""}.
      </p>
    );
  }
  const edgesFrom = new Map<string, TreeEdge[]>();
  for (const edge of edges) {
    edgesFrom.set(edge.from_subject, [...(edgesFrom.get(edge.from_subject) ?? []), edge]);
  }
  const targets = new Set(edges.map((e) => e.to_subject));
  const starts = [symptom, ...[...edgesFrom.keys()].filter((s) => s !== symptom && !targets.has(s))];
  return (
    <ul className="flex flex-col gap-1" data-testid="fault-tree">
      {starts.map((subject) => (
        <SubjectNode key={subject} subject={subject} root={root} edgesFrom={edgesFrom} seen={new Set()} />
      ))}
    </ul>
  );
}

function SubjectNode({
  subject,
  root,
  edgesFrom,
  seen,
}: {
  subject: string;
  root: string | null;
  edgesFrom: Map<string, TreeEdge[]>;
  seen: Set<string>;
}) {
  const next = new Set(seen).add(subject);
  const outgoing = seen.has(subject) ? [] : (edgesFrom.get(subject) ?? []);
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs text-foreground">{subject}</span>
        {subject === root ? (
          <Badge variant="destructive" data-testid="root-marker">
            root
          </Badge>
        ) : null}
      </div>
      {outgoing.length > 0 ? (
        <ul className="ml-3 flex flex-col gap-1 border-l border-border pl-3">
          {outgoing.map((edge) => (
            <EdgeNode key={`${edge.from_subject}->${edge.to_subject}`} edge={edge} root={root} edgesFrom={edgesFrom} seen={next} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function EdgeNode({
  edge,
  root,
  edgesFrom,
  seen,
}: {
  edge: TreeEdge;
  root: string | null;
  edgesFrom: Map<string, TreeEdge[]>;
  seen: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className="flex flex-col gap-1">
      <button
        type="button"
        className="flex items-center gap-1 self-start text-[11px] text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="edge-toggle"
      >
        {open ? <ChevronDownIcon className="size-3" /> : <ChevronRightIcon className="size-3" />}
        {edge.relation.replace("_", " ")} · {edge.established_by.length} reading
        {edge.established_by.length === 1 ? "" : "s"}
      </button>
      {open ? (
        <div className="ml-4">
          <Evidence readings={edge.readings} />
        </div>
      ) : null}
      <ul className="flex flex-col gap-1">
        <SubjectNode subject={edge.to_subject} root={root} edgesFrom={edgesFrom} seen={seen} />
      </ul>
    </li>
  );
}

const GROUPS = [
  ["supported", "Supported", "the readings confirm it"],
  ["ruled_out", "Ruled out", "a reading showed it does not hold"],
  ["unexplored", "Unexplored", "needed, and could not be tested — a refusal or no discriminating probe"],
  ["untested", "Untested", "the walk did not need them; neither ruled out nor in"],
] as const;

function Hypotheses({ groups }: { groups: InvestigationTree["hypotheses"] }) {
  return (
    <section className="flex flex-col gap-3">
      <span className="text-xs font-medium text-muted-foreground">Hypotheses</span>
      {GROUPS.map(([key, title, caption]) => {
        const items: Hypothesis[] = groups[key];
        return (
          <div key={key} className="flex flex-col gap-1" data-testid={`hypotheses-${key}`}>
            <span className="text-xs text-foreground">
              {title} ({items.length}) <span className="text-muted-foreground">— {caption}</span>
            </span>
            {items.length > 0 ? (
              <ul className="flex flex-col gap-1 pl-3">
                {items.map((h) => (
                  <li key={h.id} className="flex flex-col text-xs">
                    <span className="font-mono text-foreground">
                      {h.kind} <span className="text-muted-foreground">{h.subject}</span>
                    </span>
                    {h.reason ? <span className="text-muted-foreground">{h.reason}</span> : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
