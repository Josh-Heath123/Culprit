import { CheckIcon, CrosshairIcon, MinusIcon, SignpostIcon } from "lucide-react";

import { Card, CardBody, CardHeader, Label } from "@/components/ui/card";
import { Prose } from "@/components/ui/prose";
import { DiagnosisBadge } from "@/components/ui/status";
import { hypothesisLabel } from "@/lib/hypotheses";
import type { ConfidenceRubric, Diagnosis, Hypothesis, Symptom } from "@/lib/types";

/** The investigation's answer, as the page's heading (DELIVERY_PLAN I3:
 * the large, editorial moment on a screen is its answer). Complete: the
 * root, under the lime marker, and the walk's statement — the diagnosis
 * line. Partial: where the walk stopped, never under the word "root" or
 * "cause", and never lime, because nothing has been shown to be the fault
 * (DIAGNOSTIC_PLAN Phase 32.1, field 14). The symptom it began from sits
 * above it as a mono label: the question, outranked by the answer. */
export function DiagnosisHeading({ diagnosis, symptom }: { diagnosis: Diagnosis | null; symptom: Symptom }) {
  return (
    // A div, not <header>: the page has one header, the app's (and the
    // tour checks the investigation's id is not in it).
    <div className="flex flex-col gap-4" data-testid="diagnosis-heading">
      <div className="flex min-w-0 flex-col gap-1">
        <Label>Symptom</Label>
        <p className="font-mono text-sm wrap-anywhere text-fg-muted" data-testid="symptom-subject">
          {symptom.subject}
        </p>
        {symptom.description ? <p className="text-sm leading-relaxed text-fg-subtle">{symptom.description}</p> : null}
      </div>
      {diagnosis === null ? (
        <h1 className="text-title font-bold text-fg sm:text-display">The walk reached no diagnosis.</h1>
      ) : diagnosis.complete ? (
        <div className="flex min-w-0 flex-col gap-3 border-l-2 border-culprit pl-4 sm:pl-5" data-testid="diagnosis-line">
          <span className="flex items-center gap-1.5 font-mono text-2xs font-medium tracking-label text-culprit uppercase">
            <CrosshairIcon aria-hidden className="size-3.5" />
            Root
          </span>
          <h1
            className="font-mono text-title font-bold wrap-anywhere text-fg sm:text-display lg:text-display-lg"
            data-testid="root-subject"
          >
            {diagnosis.root_subject}
          </h1>
          <p className="max-w-3xl text-base leading-relaxed text-fg">
            <Prose text={diagnosis.statement} />
          </p>
        </div>
      ) : (
        <div className="flex min-w-0 flex-col gap-3 border-l-2 border-inconclusive-line pl-4 sm:pl-5">
          <span className="flex items-center gap-1.5 font-mono text-2xs font-medium tracking-label text-inconclusive uppercase">
            <SignpostIcon aria-hidden className="size-3.5" />
            Walk stopped at
          </span>
          <h1
            className="font-mono text-title font-bold wrap-anywhere text-fg sm:text-display lg:text-display-lg"
            data-testid="stopped-at"
          >
            {diagnosis.root_subject}
          </h1>
          <p className="max-w-3xl text-base leading-relaxed text-fg">
            <Prose text={diagnosis.statement} />
          </p>
        </div>
      )}
    </div>
  );
}

/** The rest of the walk's conclusion, under the heading. Complete: the
 * suggested fix. Partial: what it could not check, and no fix. Both: the
 * rubric. */
/** `verified`, when given, is the rubric's fourth criterion as the newest
 * verification states it (Phase 34 part 2). The stored investigation is
 * final and never says verified; whether it is comes from its own
 * append-only verifications. */
export function DiagnosisCard({
  diagnosis,
  unexplored,
  verified,
}: {
  diagnosis: Diagnosis | null;
  unexplored: Hypothesis[];
  verified?: { holds: boolean; reason: string } | null;
}) {
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
          <Partial unexplored={unexplored} />
        )}
        {diagnosis ? (
          <>
            <Rubric rubric={verified ? { ...diagnosis.confidence, verified } : diagnosis.confidence} />
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
  if (!diagnosis.remediation) {
    return <p className="text-sm text-fg-muted">The walk suggests no fix for this root.</p>;
  }
  return (
    <div className="rounded-md border border-brand-line bg-brand-tint px-3 py-2.5">
      <Label className="text-brand">Suggested fix</Label>
      <p className="mt-1 text-sm leading-relaxed text-fg">
        <Prose text={diagnosis.remediation} />
      </p>
    </div>
  );
}

function Partial({ unexplored }: { unexplored: Hypothesis[] }) {
  return (
    <div className="flex flex-col gap-2" data-testid="could-not-check">
      <h3>
        <Label>Could not check</Label>
      </h3>
      {unexplored.length === 0 ? (
        <p className="text-sm text-fg-muted">
          Every hypothesis the walk needed was tested; none of them failed, so it has nothing further to follow.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {unexplored.map((h) => (
            <li key={h.id} className="rounded-md border border-inconclusive-line bg-inconclusive-tint px-3 py-2.5">
              <p className="text-sm font-medium text-fg">{hypothesisLabel(h.kind)}</p>
              <p className="font-mono text-2xs text-fg-subtle">{h.kind}</p>
              <p className="font-mono text-2xs wrap-anywhere text-fg-muted">{h.subject}</p>
              {h.reason ? (
                <p className="mt-1 text-sm leading-relaxed text-fg-muted">
                  <Prose text={h.reason} />
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const CRITERIA = ["reproduced", "discriminated", "counterfactual", "verified"] as const;

/** §2.9's rubric as four booleans, each with the reason it holds or not.
 * Never collapsed into a score: which criterion is missing is the
 * information. */
function Rubric({ rubric }: { rubric: ConfidenceRubric }) {
  return (
    <div className="flex flex-col gap-2">
      <h3>
        <Label>Confidence — four checks, never a number</Label>
      </h3>
      <ul className="grid gap-2 sm:grid-cols-2" data-testid="rubric">
        {CRITERIA.map((name) => {
          const criterion = rubric[name];
          return (
            <li
              key={name}
              className="flex gap-2.5 rounded-md border border-line bg-surface-sunken p-3"
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
                <span className="text-xs leading-relaxed text-fg-muted">
                  <Prose text={criterion.reason} />
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
