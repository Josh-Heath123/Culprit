import { CheckIcon, CrosshairIcon, MinusIcon, SignpostIcon } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { DiagnosisBadge } from "@/components/ui/status";
import type { ConfidenceRubric, Diagnosis, Hypothesis } from "@/lib/types";

/** The walk's conclusion. Complete: the root it established, the
 * statement and a suggested fix. Partial: where the walk stopped and what
 * it could not check — never under the word "root" or "cause", and with
 * no fix, because nothing has been shown to be the fault (DIAGNOSTIC_PLAN
 * Phase 32.1, field 14). */
export function DiagnosisCard({ diagnosis, unexplored }: { diagnosis: Diagnosis | null; unexplored: Hypothesis[] }) {
  return (
    <Card aria-labelledby="diagnosis-heading" data-testid="diagnosis">
      <CardHeader
        id="diagnosis-heading"
        title="Diagnosis"
        trailing={<DiagnosisBadge complete={diagnosis ? diagnosis.complete : null} />}
      />
      <CardBody className="flex flex-col gap-5">
        {diagnosis === null ? (
          <p className="text-sm text-fg-muted">The walk reached no diagnosis.</p>
        ) : diagnosis.complete ? (
          <Complete diagnosis={diagnosis} />
        ) : (
          <Partial diagnosis={diagnosis} unexplored={unexplored} />
        )}
        {diagnosis ? (
          <>
            <Rubric rubric={diagnosis.confidence} />
            <p className="text-2xs text-fg-subtle">
              The statement is the walk's own, built from its readings; no model wrote it. Culprit does not
              generate prose summaries.
            </p>
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Complete({ diagnosis }: { diagnosis: Diagnosis }) {
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-2xs font-semibold tracking-widest text-highlight uppercase">
          <CrosshairIcon aria-hidden className="size-3.5" />
          Root
        </span>
        <p className="font-mono text-base font-medium wrap-anywhere text-fg sm:text-lg" data-testid="root-subject">
          {diagnosis.root_subject}
        </p>
      </div>
      <p className="text-sm leading-relaxed text-fg">{diagnosis.statement}</p>
      {diagnosis.remediation ? (
        <div className="rounded-md border border-brand-line bg-brand-tint px-3 py-2.5">
          <span className="text-2xs font-semibold tracking-widest text-brand uppercase">Suggested fix</span>
          <p className="mt-1 text-sm leading-relaxed text-fg">{diagnosis.remediation}</p>
        </div>
      ) : null}
    </>
  );
}

function Partial({ diagnosis, unexplored }: { diagnosis: Diagnosis; unexplored: Hypothesis[] }) {
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-2xs font-semibold tracking-widest text-inconclusive uppercase">
          <SignpostIcon aria-hidden className="size-3.5" />
          Walk stopped at
        </span>
        <p className="font-mono text-base font-medium wrap-anywhere text-fg sm:text-lg" data-testid="stopped-at">
          {diagnosis.root_subject}
        </p>
      </div>
      <p className="text-sm leading-relaxed text-fg">{diagnosis.statement}</p>
      <div className="flex flex-col gap-2" data-testid="could-not-check">
        <h3 className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">Could not check</h3>
        {unexplored.length === 0 ? (
          <p className="text-sm text-fg-muted">
            Every hypothesis the walk needed was tested; none of them failed, so it has nothing further to
            follow.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {unexplored.map((h) => (
              <li key={h.id} className="rounded-md border border-inconclusive-line bg-inconclusive-tint px-3 py-2.5">
                <p className="font-mono text-xs wrap-anywhere text-fg">
                  {h.kind} <span className="text-fg-muted">{h.subject}</span>
                </p>
                {h.reason ? <p className="mt-1 text-sm leading-relaxed text-fg-muted">{h.reason}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

const CRITERIA = ["reproduced", "discriminated", "counterfactual", "verified"] as const;

/** §2.9's rubric as four booleans, each with the reason it holds or not.
 * Never collapsed into a score: which criterion is missing is the
 * information. */
function Rubric({ rubric }: { rubric: ConfidenceRubric }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">
        Confidence — four checks, never a number
      </h3>
      <ul className="grid gap-2 sm:grid-cols-2" data-testid="rubric">
        {CRITERIA.map((name) => {
          const criterion = rubric[name];
          return (
            <li
              key={name}
              className="flex gap-2.5 rounded-md border border-line bg-surface-2 p-3"
              data-criterion={name}
              data-holds={criterion.holds}
            >
              <span
                className={
                  criterion.holds
                    ? "mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-pass-tint text-pass"
                    : "mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-3 text-fg-subtle"
                }
                aria-hidden
              >
                {criterion.holds ? <CheckIcon className="size-3.5" /> : <MinusIcon className="size-3.5" />}
              </span>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium text-fg">
                  {name} <span className="font-normal text-fg-muted">— {criterion.holds ? "yes" : "no"}</span>
                </span>
                <span className="text-xs leading-relaxed text-fg-muted">{criterion.reason}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
