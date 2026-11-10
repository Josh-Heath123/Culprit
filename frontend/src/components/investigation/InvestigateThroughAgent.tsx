import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAgents } from "@/hooks/useAgents";
import { createTask, fetchTask } from "@/lib/api";
import { grantWords, INVESTIGATION_NEEDS, missingForInvestigation } from "@/lib/grants";
import type { AgentSummary, TaskView } from "@/lib/types";

/** Open an investigation through an agent (Phase 33 part 3): choose an agent
 * and a symptom, watch the task, and land on the investigation when the
 * agent's walk is stored. The walk runs in the agent, where the system is;
 * the control plane only addresses the task and stores what comes back.
 *
 * When no agent may use what an investigation needs, this says which grant
 * is missing and where to give it, and starts nothing. */
export function InvestigateThroughAgent() {
  const { agents, isPending } = useAgents();
  const active = useMemo(() => agents.filter((agent) => agent.revoked_at == null), [agents]);

  const [agentId, setAgentId] = useState("");
  const [environment, setEnvironment] = useState("");
  const [symptom, setSymptom] = useState("");
  const [from, setFrom] = useState("");
  const [task, setTask] = useState<{ agentId: string; id: string } | null>(null);

  // Default to the first agent, and to its first environment.
  const agent: AgentSummary | undefined = active.find((a) => a.id === agentId) ?? active[0];
  const environments = agent ? Object.keys(agent.reported_grants).sort() : [];
  const env = environments.includes(environment) ? environment : (environments[0] ?? "");
  const missing = agent
    ? missingForInvestigation(agent.reported_grants[env] ?? [], agent.allowances[env] ?? [])
    : { notAllowed: [], notHeld: [] };
  const ready = agent != null && env !== "" && missing.notAllowed.length + missing.notHeld.length === 0;

  const start = useMutation({
    mutationFn: () =>
      createTask(agent!.id, {
        environment: env,
        kind: "diagnose",
        diagnose: { symptom: symptom.trim(), from: from.trim() || null },
      }),
    onSuccess: (created) => setTask({ agentId: agent!.id, id: created.id }),
  });

  if (isPending) return null;

  return (
    <Card aria-labelledby="investigate-heading" data-testid="investigate-through-agent">
      <CardHeader id="investigate-heading" title="Investigate through an agent" />
      <CardBody className="flex flex-col gap-4">
        {active.length === 0 ? (
          <p className="text-sm text-fg-muted" data-testid="investigate-unavailable">
            No agent is paired, so nothing can run an investigation yet.{" "}
            <Link to="/settings/agents" className="text-brand underline-offset-4 hover:underline">
              Pair one under Settings → Agents
            </Link>
            .
          </p>
        ) : task ? (
          <TaskProgress agentId={task.agentId} taskId={task.id} onReset={() => setTask(null)} />
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (ready && symptom.trim()) start.mutate();
            }}
          >
            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="investigate-agent" className="text-xs font-medium text-fg-muted">
                  Agent
                </label>
                <Select id="investigate-agent" value={agent?.id ?? ""} onChange={(e) => setAgentId(e.target.value)}>
                  {active.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.id}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="investigate-environment" className="text-xs font-medium text-fg-muted">
                  Environment
                </label>
                <Select id="investigate-environment" value={env} onChange={(e) => setEnvironment(e.target.value)}>
                  {environments.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="investigate-symptom" className="text-xs font-medium text-fg-muted">
                  Symptom
                </label>
                <Input
                  id="investigate-symptom"
                  autoComplete="off"
                  placeholder="POST http://order-service:8001/orders, or a component"
                  value={symptom}
                  onChange={(e) => setSymptom(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="investigate-from" className="text-xs font-medium text-fg-muted">
                  Runs inside <span className="font-normal text-fg-subtle">(optional)</span>
                </label>
                <Input
                  id="investigate-from"
                  autoComplete="off"
                  placeholder="the component the agent runs inside"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                />
              </div>
            </div>

            {!ready && agent ? <WhyNot agent={agent} environment={env} missing={missing} /> : null}

            {start.isError ? (
              <p role="alert" className="text-xs text-fail">
                {start.error instanceof Error ? start.error.message : "The investigation was not started."}
              </p>
            ) : null}

            <Button type="submit" className="self-start" disabled={!ready || !symptom.trim() || start.isPending}>
              {start.isPending ? "Starting…" : "Start the investigation"}
            </Button>
          </form>
        )}
      </CardBody>
    </Card>
  );
}

function WhyNot({
  agent,
  environment,
  missing,
}: {
  agent: AgentSummary;
  environment: string;
  missing: { notAllowed: string[]; notHeld: string[] };
}) {
  return (
    <div role="status" className="flex flex-col gap-1.5 rounded-md border border-degrades-line bg-degrades-tint p-3 text-sm text-fg" data-testid="investigate-unavailable">
      <p>
        An investigation needs {INVESTIGATION_NEEDS.map((g) => `${g}`).join(" and ")}, to tell whether a connection or
        a service fails. {agent.id} cannot use {missing.notAllowed.length + missing.notHeld.length === 1 ? "one" : "them"}{" "}
        in {environment || "any environment"}:
      </p>
      <ul className="flex flex-col gap-1 text-xs">
        {missing.notAllowed.map((grant) => (
          <li key={grant}>
            <code className="font-mono">{grant}</code> ({grantWords(grant)}) — it holds this but is not allowed it.{" "}
            <Link to="/settings/agents" className="text-brand underline-offset-4 hover:underline">
              Allow it under Settings → Agents
            </Link>
            .
          </li>
        ))}
        {missing.notHeld.map((grant) => (
          <li key={grant}>
            <code className="font-mono">{grant}</code> ({grantWords(grant)}) — its own configuration does not grant
            this, and nothing here can give it. Add it to the agent's configuration and pair it as a new agent: what
            an agent holds is recorded when it pairs.
          </li>
        ))}
      </ul>
      <p className="text-xs text-fg-muted">Nothing has been started.</p>
    </div>
  );
}

function TaskProgress({ agentId, taskId, onReset }: { agentId: string; taskId: string; onReset: () => void }) {
  const navigate = useNavigate();
  const { data, isError, error } = useQuery({
    queryKey: ["task", agentId, taskId],
    queryFn: () => fetchTask(agentId, taskId),
    refetchInterval: (query) => (query.state.data?.completed_at ? false : 1_500),
  });

  const landed = data?.investigation_id ?? null;
  useEffect(() => {
    if (landed) navigate(`/investigations/${encodeURIComponent(landed)}`);
  }, [landed, navigate]);

  return (
    <div className="flex flex-col gap-3" data-testid="investigate-progress">
      <ol className="flex flex-col gap-1.5 text-sm" aria-label="Progress">
        <Step done label={`Task ${taskId} addressed to ${agentId}`} />
        <Step done={data?.claimed_at != null} label="Claimed by the agent" />
        <Step done={data?.completed_at != null} label={stepLabel(data)} />
      </ol>
      {isError ? (
        <p role="alert" className="text-xs text-fail">
          {error instanceof Error ? error.message : "The task could not be read."}
        </p>
      ) : null}
      {data?.completed_at && !landed ? (
        <div className="flex flex-col gap-2">
          <p role="alert" className="text-sm text-fail">
            The agent {data.outcome === "refused" ? "refused the task" : "could not finish it"}
            {data.reason ? `: ${data.reason}` : "."}
          </p>
          <Button variant="outline" size="sm" className="self-start" onClick={onReset}>
            Start another
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function stepLabel(task: TaskView | undefined): string {
  if (!task?.claimed_at) return "Walk, and store the investigation";
  if (!task.completed_at) return "Walking the request path…";
  return task.investigation_id ? "Investigation stored — opening it" : "Finished without an investigation";
}

function Step({ done, label }: { done: boolean; label: string }) {
  return (
    <li className="flex items-center gap-2">
      <span
        aria-hidden="true"
        className={done ? "size-2 rounded-full bg-pass" : "size-2 rounded-full border border-line-strong"}
      />
      <span className={done ? "text-fg" : "text-fg-muted"}>
        {label}
        <span className="sr-only">{done ? " (done)" : " (waiting)"}</span>
      </span>
    </li>
  );
}
