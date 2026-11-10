import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Page } from "@/components/layout/Page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { EmptyPanel, ErrorPanel, LoadingRows } from "@/components/ui/states";
import { useAgents } from "@/hooks/useAgents";
import { createPairingCode, revokeAgent, setAllowance } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";
import { diffGrants, grantWords } from "@/lib/grants";
import type { AgentSummary, PairingCodeCreated } from "@/lib/types";

/** Settings → Agents (Phase 33 part 3), admins only. Every paired agent with
 * its status, its last signed request, the grants it reports and what it is
 * allowed; a pairing code, shown once; an allowance edited with the change
 * shown as a diff before it is saved; revocation, after confirmation.
 *
 * Nothing here can widen what an agent may do: the API allows only grants
 * the agent itself reports holding, and the agent intersects any allowance
 * with its own configuration again (docs/PERMISSIONS.md). */
export function SettingsAgents() {
  const { agents, isPending, isError, error, refetch } = useAgents();

  return (
    <Page
      eyebrow="Settings"
      title="Agents"
      description={
        <>
          An agent runs probes where your services are, under the grants its own configuration gives it. Here you
          pair one, choose which of those grants it may use, and revoke it. You can narrow what it does; nothing here
          can widen it.
        </>
      }
    >
      <PairingCard />

      {isPending ? <LoadingRows label="Loading agents" rows={2} /> : null}
      {isError ? (
        <ErrorPanel
          title="Couldn't load agents."
          message={error instanceof Error ? error.message : "The request failed."}
          onRetry={() => refetch()}
        />
      ) : null}
      {!isPending && !isError && agents.length === 0 ? (
        <EmptyPanel title="No agents yet">
          Create a pairing code above, then run <code className="font-mono text-xs text-fg">culprit agent pair</code>{" "}
          where the agent is. It appears here once it has paired.
        </EmptyPanel>
      ) : null}

      {agents.length > 0 ? (
        <Card aria-labelledby="agents-heading">
          <CardHeader
            id="agents-heading"
            title="Paired agents"
            trailing={<span className="text-2xs text-fg-subtle">{agents.length}</span>}
          />
          <ul className="divide-y divide-line">
            {agents.map((agent) => (
              <AgentRow key={agent.id} agent={agent} />
            ))}
          </ul>
        </Card>
      ) : null}
    </Page>
  );
}

function PairingCard() {
  const [created, setCreated] = useState<PairingCodeCreated | null>(null);
  const mutation = useMutation({ mutationFn: createPairingCode, onSuccess: setCreated });

  return (
    <Card aria-labelledby="pair-heading">
      <CardHeader id="pair-heading" title="Pair an agent" />
      <CardBody className="flex flex-col gap-3">
        <p className="text-sm text-fg-muted">
          A pairing code works once and expires after 15 minutes. It is shown once: only its hash is kept.
        </p>
        {mutation.isError ? (
          <p role="alert" className="text-xs text-fail">
            {mutation.error instanceof Error ? mutation.error.message : "Couldn't create a pairing code."}
          </p>
        ) : null}
        <Button className="self-start" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create a pairing code"}
        </Button>
      </CardBody>

      {created ? (
        <Dialog open onOpenChange={(open) => !open && setCreated(null)}>
          <DialogContent aria-describedby="pairing-code-help" className="flex flex-col gap-4 p-5 sm:p-6">
            <DialogTitle className="text-base">Pairing code</DialogTitle>
            <p
              className="rounded-md border border-line bg-surface-2 px-3 py-2 text-center font-mono text-lg tracking-wider break-all text-fg select-all"
              data-testid="pairing-code"
            >
              {created.code}
            </p>
            <div id="pairing-code-help" className="flex flex-col gap-2 text-sm text-fg-muted">
              <p>
                Works once, until <time dateTime={created.expires_at}>{formatDateTime(created.expires_at)}</time>. Copy
                it now — it will not be shown again.
              </p>
              <p>Where the agent runs, after <code className="font-mono text-xs text-fg">culprit agent init</code>:</p>
              <pre className="overflow-x-auto rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-fg">
                culprit agent pair --config agent.yaml --code -
              </pre>
              <p className="text-xs text-fg-subtle">
                <code className="font-mono">--code -</code> reads the code from standard input, so it is in neither
                the shell's history nor the process list.
              </p>
            </div>
            <Button className="self-end" size="sm" onClick={() => setCreated(null)}>
              Done
            </Button>
          </DialogContent>
        </Dialog>
      ) : null}
    </Card>
  );
}

function AgentRow({ agent }: { agent: AgentSummary }) {
  const [editing, setEditing] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const revoked = agent.revoked_at != null;
  const environments = Object.keys(agent.reported_grants).sort();

  return (
    <li className="flex flex-col gap-4 px-4 py-4 sm:px-5" data-testid="agent-row" data-agent={agent.id}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm wrap-anywhere text-fg">{agent.id}</span>
            {revoked ? (
              <Badge variant="refused" data-testid="agent-status">
                revoked
              </Badge>
            ) : (
              <Badge variant="pass" data-testid="agent-status">
                paired
              </Badge>
            )}
          </div>
          <span className="text-xs text-fg-subtle" data-testid="agent-last-request">
            {agent.last_request_at ? (
              <>
                Last signed request{" "}
                <time dateTime={agent.last_request_at}>{formatDateTime(agent.last_request_at)}</time>
              </>
            ) : (
              "No signed request yet"
            )}
            {" · "}paired <time dateTime={agent.registered_at}>{formatDateTime(agent.registered_at)}</time>
            {revoked && agent.revoked_at ? (
              <>
                {" · "}revoked <time dateTime={agent.revoked_at}>{formatDateTime(agent.revoked_at)}</time>
              </>
            ) : null}
          </span>
        </div>
        {revoked ? null : (
          <Button variant="destructive" size="sm" className="self-start" onClick={() => setRevoking(true)}>
            Revoke
          </Button>
        )}
      </div>

      {environments.map((environment) => (
        <EnvironmentGrants
          key={environment}
          agentId={agent.id}
          environment={environment}
          reported={agent.reported_grants[environment] ?? []}
          allowed={agent.allowances[environment] ?? []}
          revoked={revoked}
          onEdit={() => setEditing(environment)}
        />
      ))}

      {editing ? (
        <AllowanceDialog
          agent={agent}
          environment={editing}
          reported={agent.reported_grants[editing] ?? []}
          allowed={agent.allowances[editing] ?? []}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {revoking ? <RevokeDialog agentId={agent.id} onClose={() => setRevoking(false)} /> : null}
    </li>
  );
}

function EnvironmentGrants({
  agentId,
  environment,
  reported,
  allowed,
  revoked,
  onEdit,
}: {
  agentId: string;
  environment: string;
  reported: string[];
  allowed: string[];
  revoked: boolean;
  onEdit: () => void;
}) {
  const headingId = `grants-${agentId}-${environment}`;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 rounded-md border border-line p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-xs font-semibold text-fg">
          {environment}{" "}
          <span className="font-normal text-fg-subtle">
            · allowed {allowed.length} of the {reported.length} it reports
          </span>
        </h3>
        {revoked ? null : (
          <Button variant="outline" size="sm" onClick={onEdit}>
            Edit allowance
          </Button>
        )}
      </div>
      <ul className="flex flex-col gap-1.5" data-testid="agent-grants" data-environment={environment}>
        {reported.map((grant) => {
          const isAllowed = allowed.includes(grant);
          return (
            <li key={grant} className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
              <Badge variant={isAllowed ? "primary" : "outline"} className="self-start">
                {isAllowed ? "allowed" : "not allowed"}
              </Badge>
              <span className="text-sm text-fg">{grantWords(grant)}</span>
              <code className="font-mono text-2xs text-fg-subtle">{grant}</code>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function AllowanceDialog({
  agent,
  environment,
  reported,
  allowed,
  onClose,
}: {
  agent: AgentSummary;
  environment: string;
  reported: string[];
  allowed: string[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<string[]>(allowed);
  const diff = diffGrants(allowed, chosen);
  const changed = diff.added.length + diff.removed.length > 0;

  const mutation = useMutation({
    mutationFn: () => setAllowance(agent.id, environment, chosen),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      onClose();
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby="allowance-help" className="max-h-dvh overflow-y-auto p-5 sm:p-6">
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (changed) mutation.mutate();
          }}
        >
          <div>
            <DialogTitle className="text-base">
              Allowance for <span className="font-mono">{agent.id}</span> in {environment}
            </DialogTitle>
            <p id="allowance-help" className="mt-1 text-xs text-fg-muted">
              Only the grants this agent reports are offered. It takes effect on the agent's next task, with no
              restart.
            </p>
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-xs font-medium text-fg-muted">May use</legend>
            {reported.map((grant) => (
              <label key={grant} className="flex items-start gap-2 text-sm text-fg">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={chosen.includes(grant)}
                  onChange={(event) =>
                    setChosen((current) =>
                      event.target.checked ? [...current, grant] : current.filter((g) => g !== grant),
                    )
                  }
                />
                <span className="flex flex-col">
                  <span>{grantWords(grant)}</span>
                  <code className="font-mono text-2xs text-fg-subtle">{grant}</code>
                </span>
              </label>
            ))}
          </fieldset>

          <section aria-labelledby="allowance-diff-heading" className="flex flex-col gap-1.5" data-testid="allowance-diff">
            <h4 id="allowance-diff-heading" className="text-xs font-medium text-fg-muted">
              The change
            </h4>
            {changed ? (
              <ul className="flex flex-col gap-1 rounded-md border border-line bg-surface-2 p-3 font-mono text-xs">
                {diff.added.map((grant) => (
                  <li key={`+${grant}`} className="text-pass" data-change="added">
                    + {grant} <span className="font-sans text-fg-muted">— {grantWords(grant)}</span>
                  </li>
                ))}
                {diff.removed.map((grant) => (
                  <li key={`-${grant}`} className="text-fail" data-change="removed">
                    − {grant} <span className="font-sans text-fg-muted">— {grantWords(grant)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-fg-subtle">No change yet.</p>
            )}
          </section>

          {mutation.isError ? (
            <p role="alert" className="text-xs text-fail">
              {mutation.error instanceof Error ? mutation.error.message : "That change was not saved."}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={!changed || mutation.isPending}>
              {mutation.isPending ? "Saving…" : "Save allowance"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RevokeDialog({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => revokeAgent(agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      onClose();
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby="revoke-help" className="flex flex-col gap-4 p-5 sm:p-6">
        <DialogTitle className="text-base">
          Revoke <span className="font-mono">{agentId}</span>?
        </DialogTitle>
        <p id="revoke-help" className="text-sm text-fg-muted">
          Its very next request is refused, and every one after. It cannot be undone: to use this machine again, pair
          a new agent with a new key.
        </p>
        {mutation.isError ? (
          <p role="alert" className="text-xs text-fail">
            {mutation.error instanceof Error ? mutation.error.message : "The agent was not revoked."}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? "Revoking…" : "Revoke agent"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
