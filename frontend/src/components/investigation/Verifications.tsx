import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, MinusIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Prose } from "@/components/ui/prose";
import { Select } from "@/components/ui/select";
import { VerificationBadge } from "@/components/ui/status";
import { Textarea } from "@/components/ui/textarea";
import { useAgents } from "@/hooks/useAgents";
import { createTask, fetchTask } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import type { Change, InvestigationTree, StoredVerification, TaskView } from "@/lib/types";

/** Whether a fix fixed it (Phase 34 part 2): every verification of this
 * investigation, newest first. Each is its own append-only record; the
 * investigation is never edited, and the rubric's `verified` above is the
 * newest one's verdict. Nothing here judges: the verdict is the one
 * `culprit verify` or the agent reached, and the API re-judged. */
export function Verifications({
  investigation,
  verifications,
  isAdmin,
}: {
  investigation: InvestigationTree;
  verifications: StoredVerification[];
  isAdmin: boolean;
}) {
  const latest = verifications[0];
  return (
    <Card aria-labelledby="verifications-heading" data-testid="verifications">
      <CardHeader
        id="verifications-heading"
        title="Verification"
        trailing={latest ? <VerificationBadge verdict={latest.verification.verdict} /> : null}
      />
      <CardBody className="flex flex-col gap-4">
        {verifications.length === 0 ? (
          <p className="text-sm text-fg-muted" data-testid="no-verifications">
            No change has been verified yet. After a fix is applied, a verification measures every reading this
            investigation took again, twice, and compares the environment with the record of it taken at diagnosis.
          </p>
        ) : (
          <ol className="flex flex-col gap-3">
            {verifications.map((stored, index) => (
              <VerificationItem key={stored.verification.id} stored={stored} newest={index === 0} />
            ))}
          </ol>
        )}
        {isAdmin ? <AskToVerify investigation={investigation} /> : null}
      </CardBody>
    </Card>
  );
}

function changeWords(change: Change): string {
  if (change.kind === "commit") return `commit ${change.ref}`;
  if (change.kind === "action") return `action: ${change.description}`;
  return change.subject ?? change.kind;
}

const CLAUSES = [
  ["failing_now_passes", "What failed now passes, on both runs"],
  ["no_regressions", "What passed still passes"],
  ["changes_explained", "Every change in the environment is explained by what was named"],
] as const;

function VerificationItem({ stored, newest }: { stored: StoredVerification; newest: boolean }) {
  const { verification } = stored;
  return (
    <li
      className="flex flex-col gap-2.5 rounded-md border border-line bg-surface-2 p-3"
      data-testid="verification"
      data-verdict={verification.verdict}
    >
      <div className="flex flex-wrap items-center gap-2">
        <VerificationBadge verdict={verification.verdict} />
        {newest ? <span className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">Newest</span> : null}
        <time dateTime={verification.verified_at} className="text-xs text-fg-muted">
          {formatDateTime(verification.verified_at)}
        </time>
      </div>
      <p className="text-sm leading-relaxed text-fg">
        <Prose text={verification.reason} />
      </p>
      <ul className="flex flex-col gap-1" aria-label="The three conditions of verified">
        {CLAUSES.map(([name, label]) => (
          <li key={name} className="flex items-center gap-2 text-xs" data-clause={name} data-holds={verification[name]}>
            <span aria-hidden className={verification[name] ? "text-pass" : "text-fg-subtle"}>
              {verification[name] ? <CheckIcon className="size-3.5" /> : <MinusIcon className="size-3.5" />}
            </span>
            <span className={verification[name] ? "text-fg" : "text-fg-muted"}>
              {label} — {verification[name] ? "yes" : "no"}
            </span>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-3 gap-x-3 gap-y-1.5 text-xs">
        <dt className="text-fg-subtle">Change named</dt>
        <dd className="col-span-2 font-mono wrap-anywhere text-fg" data-testid="verification-changes">
          {verification.applied_change.length === 0
            ? "none"
            : verification.applied_change.map((change) => changeWords(change)).join("; ")}
        </dd>
        <dt className="text-fg-subtle">Measured again</dt>
        <dd className="col-span-2 text-fg">
          {verification.reran.length} reading{verification.reran.length === 1 ? "" : "s"}, each twice
        </dd>
        <dt className="text-fg-subtle">Fault</dt>
        <dd className="col-span-2 text-fg" data-testid="verification-source">
          {stored.source === "planted" ? "planted on purpose (a drill)" : "on a real system"}
        </dd>
        <dt className="text-fg-subtle">Recorded by</dt>
        <dd className="col-span-2 font-mono wrap-anywhere text-fg-muted">{stored.submitted_by}</dd>
      </dl>
    </li>
  );
}

/** An admin asks an agent to verify, naming what was applied. The agent
 * that diagnosed the investigation holds its record of before, so it is the
 * default; any other answers inconclusive, and says why. */
function AskToVerify({ investigation }: { investigation: InvestigationTree }) {
  const { agents, isPending } = useAgents();
  const active = useMemo(() => agents.filter((agent) => agent.revoked_at == null), [agents]);
  const diagnosedBy = investigation.submitted_by.startsWith("agent:")
    ? investigation.submitted_by.slice("agent:".length)
    : null;
  const [agentId, setAgentId] = useState<string | null>(null);
  const [changes, setChanges] = useState("");
  const [source, setSource] = useState<"planted" | "real" | null>(null);
  const [task, setTask] = useState<{ agentId: string; id: string } | null>(null);

  const chosen = agentId ?? (active.some((a) => a.id === diagnosedBy) ? diagnosedBy : (active[0]?.id ?? null));
  const lines = changes
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const start = useMutation({
    mutationFn: () =>
      createTask(chosen!, {
        environment: investigation.environment,
        kind: "verify",
        verify: { investigation_id: investigation.id, changes: lines, source: source! },
      }),
    onSuccess: (created) => setTask({ agentId: chosen!, id: created.id }),
  });

  if (isPending) return null;
  if (active.length === 0) {
    return (
      <p className="text-xs text-fg-muted" data-testid="verify-unavailable">
        No agent is paired, so none can be asked to verify. `culprit verify` runs the same check from where the
        diagnosis ran.
      </p>
    );
  }
  if (task) {
    return <VerifyProgress agentId={task.agentId} taskId={task.id} investigationId={investigation.id} onReset={() => setTask(null)} />;
  }
  return (
    <form
      className="flex flex-col gap-3 border-t border-line pt-4"
      data-testid="ask-to-verify"
      onSubmit={(event) => {
        event.preventDefault();
        if (chosen && source) start.mutate();
      }}
    >
      <h3 className="text-sm font-medium text-fg">Ask an agent to verify a fix</h3>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="verify-agent" className="text-xs font-medium text-fg-muted">
          Agent
        </label>
        <Select id="verify-agent" value={chosen ?? ""} onChange={(e) => setAgentId(e.target.value)}>
          {active.map((a) => (
            <option key={a.id} value={a.id}>
              {a.id}
              {a.id === diagnosedBy ? " — diagnosed this" : ""}
            </option>
          ))}
        </Select>
        {chosen !== diagnosedBy ? (
          <p className="text-xs text-fg-muted" data-testid="verify-not-the-diagnosing-agent">
            {diagnosedBy
              ? `This was diagnosed by ${diagnosedBy}. Another agent holds no record of before, and will answer inconclusive.`
              : "This was not diagnosed by an agent, so no agent holds its record of before: the answer will be inconclusive. Run culprit verify where the diagnosis ran."}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="verify-changes" className="text-xs font-medium text-fg-muted">
          What was applied <span className="font-normal text-fg-subtle">(one per line)</span>
        </label>
        <Textarea
          id="verify-changes"
          rows={3}
          className="font-mono text-xs"
          placeholder={"config:order-service/INVENTORY_TOKEN\nimage:inventory-service\ncommit:9f2c4e1\naction:restarted inventory-service"}
          value={changes}
          onChange={(e) => setChanges(e.target.value)}
        />
        <p className="text-2xs text-fg-subtle">
          As <code className="font-mono">culprit verify --change</code> takes them. With nothing named, the verdict
          is inconclusive.
        </p>
      </div>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-xs font-medium text-fg-muted">Was this fault planted on purpose?</legend>
        <label className="flex items-center gap-2 text-sm text-fg">
          <input type="radio" name="verify-source" checked={source === "planted"} onChange={() => setSource("planted")} />
          Yes — a drill; it counts as a planted fault
        </label>
        <label className="flex items-center gap-2 text-sm text-fg">
          <input type="radio" name="verify-source" checked={source === "real"} onChange={() => setSource("real")} />
          No — it happened on a real system
        </label>
      </fieldset>
      {start.isError ? (
        <p role="alert" className="text-xs text-fail">
          {start.error instanceof Error ? start.error.message : "The verification was not started."}
        </p>
      ) : null}
      <Button type="submit" className="self-start" disabled={!chosen || !source || start.isPending}>
        {start.isPending ? "Starting…" : "Verify"}
      </Button>
    </form>
  );
}

function VerifyProgress({
  agentId,
  taskId,
  investigationId,
  onReset,
}: {
  agentId: string;
  taskId: string;
  investigationId: string;
  onReset: () => void;
}) {
  const queryClient = useQueryClient();
  const { data, isError, error } = useQuery({
    queryKey: ["task", agentId, taskId],
    queryFn: async () => {
      const task = await fetchTask(agentId, taskId);
      if (task.completed_at) await queryClient.invalidateQueries({ queryKey: ["verifications", investigationId] });
      return task;
    },
    refetchInterval: (query) => (query.state.data?.completed_at ? false : 1_500),
  });
  const result = data?.result as { verdict?: string; verification_id?: string } | null | undefined;

  return (
    <div className="flex flex-col gap-2 border-t border-line pt-4" data-testid="verify-progress">
      <p className="text-sm text-fg">{progressWords(data)}</p>
      {isError ? (
        <p role="alert" className="text-xs text-fail">
          {error instanceof Error ? error.message : "The task could not be read."}
        </p>
      ) : null}
      {data?.completed_at ? (
        <>
          {!result?.verification_id && data.reason ? (
            <p className="text-sm text-fg-muted" data-testid="verify-answer">
              <Prose text={data.reason} />
            </p>
          ) : null}
          <Button variant="outline" size="sm" className="self-start" onClick={onReset}>
            Verify again
          </Button>
        </>
      ) : null}
    </div>
  );
}

function progressWords(task: TaskView | undefined): string {
  if (!task?.claimed_at) return `Task addressed; waiting for the agent to claim it.`;
  if (!task.completed_at) return "The agent is measuring every reading again…";
  const result = task.result as { verdict?: string; verification_id?: string } | null;
  if (result?.verification_id) return `Verification ${result.verification_id} stored — it is listed above.`;
  if (result?.verdict) return `The agent answered ${result.verdict}, and measured nothing.`;
  return task.outcome === "refused" ? "The agent refused the task." : "The agent could not finish the task.";
}
