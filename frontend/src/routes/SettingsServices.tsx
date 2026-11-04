import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Page } from "@/components/layout/Page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ErrorPanel, LoadingRows } from "@/components/ui/states";
import {
  useAcceptTopologySuggestion,
  useDismissTopologySuggestion,
  useTopologySuggestions,
} from "@/hooks/useTopologySuggestions";
import { connectionsBySource, useComponents, useConnections } from "@/hooks/useModel";
import { formatDate } from "@/lib/datetime";
import {
  createComponent,
  createConnection,
  createKey,
  deleteConnection,
  patchComponent,
  patchConnection,
  revokeKey,
} from "@/lib/api";
import type {
  ComponentKind,
  ComponentOut,
  ConnectionKind,
  ConnectionOut,
  Criticality,
  TopologySuggestionOut,
} from "@/lib/types";

/** Phase 27's closed sets, mirrored from culprit_model.graph. Closed on
 * purpose: `kind` selects a probe in Phase 31 and `criticality` feeds
 * divergence severity in Phase 29, so a free-text field here would push
 * both decisions onto whoever typed the row. The API rejects anything
 * off these lists (422), and the migration's CHECK constraints reject it
 * again at the database. */
const COMPONENT_KINDS: ComponentKind[] = [
  "service",
  "frontend",
  "database",
  "queue",
  "external_api",
  "job",
  "cache",
  "object_store",
];

const CONNECTION_KINDS: ConnectionKind[] = [
  "http",
  "grpc",
  "sql",
  "message",
  "cache",
  "dns",
  "auth",
];

/** `unknown` is a real value, not a placeholder — see
 * culprit_model.graph.Criticality. It is shown as "unclassified" rather
 * than hidden, because an unclassified edge still counts as on the
 * request path and an operator should be able to see which ones nobody
 * has decided about yet. */
const CRITICALITIES: Criticality[] = ["on_request_path", "background", "unknown"];

const CRITICALITY_LABEL: Record<Criticality, string> = {
  on_request_path: "on request path",
  background: "background",
  unknown: "unclassified",
};

const SERVICE_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]{0,62}$/;

/** Registered once, then never retrievable again (api/app/model/schemas.py's
 * ComponentCreateResponse, api/app/registry/schemas.py's KeyCreateResponse)
 * — this modal is the only place a
 * plaintext key is ever shown, so it has to be unmissable and say so
 * plainly, not just close quietly like every other dialog in the app. */
function NewKeyDialog({
  serviceName,
  apiKey,
  onClose,
}: {
  serviceName: string;
  apiKey: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent aria-describedby={undefined} className="p-5 sm:p-6">
        <div className="flex flex-col gap-4">
          <div>
            <DialogTitle className="text-base">New key for {serviceName}</DialogTitle>
            <p className="mt-1 text-xs text-fail">
              This is shown once. It cannot be retrieved again — copy it now.
            </p>
          </div>
          <code className="wrap-anywhere rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-fg">
            {apiKey}
          </code>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(apiKey);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
            <Button size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Registers a component, then declares its `http` connections to the
 * ones ticked under "Depends on".
 *
 * Two steps, not one: `POST /model/components` does not take
 * connections (the `/services` alias's `depends_on` did, until Phase 30
 * removed it). The order matters for one reason — the new component's
 * ingest key is returned exactly once, by the first call. So the key is
 * shown whatever happens to the connections, and a connection that fails
 * is reported by name rather than swallowing a key the operator will
 * never see again. */
function AddServiceForm({ existing }: { existing: ComponentOut[] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [kind, setKind] = useState<ComponentKind>("service");
  const [metrics, setMetrics] = useState("");
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  const [issuedKey, setIssuedKey] = useState<{ serviceName: string; apiKey: string } | null>(null);
  const [failedConnections, setFailedConnections] = useState<string[]>([]);

  const mutation = useMutation({
    mutationFn: async () => {
      const created = await createComponent({
        name,
        display_name: displayName.trim() || null,
        kind,
        monitored_metrics: metrics
          .split(",")
          .map((m) => m.trim())
          .filter(Boolean),
        sort_order: 0,
      });
      const failed: string[] = [];
      for (const target of dependsOn) {
        try {
          await createConnection({
            from_component: created.component.name,
            to_component: target,
            kind: "http",
            criticality: "unknown",
            declared_by: "culprit_yaml",
          });
        } catch {
          failed.push(target);
        }
      }
      return { created, failed };
    },
    onSuccess: ({ created, failed }) => {
      queryClient.invalidateQueries({ queryKey: ["model"] });
      setIssuedKey({ serviceName: created.component.name, apiKey: created.api_key });
      setFailedConnections(failed);
      setName("");
      setDisplayName("");
      setKind("service");
      setMetrics("");
      setDependsOn([]);
    },
  });

  const nameValid = SERVICE_NAME_PATTERN.test(name);

  return (
    <>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (nameValid) mutation.mutate();
        }}
        className="flex flex-col gap-4 rounded-lg border border-line bg-surface-1 p-4 sm:p-5"
      >
        <p className="text-sm font-semibold text-fg">Register a component</p>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-service-name" className="text-xs font-medium text-fg-muted">
            Name — must match the OTel <code>service.name</code> resource attribute exactly
          </label>
          <Input
            id="new-service-name"
            placeholder="checkout-api"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          {name && !nameValid ? (
            <p className="text-xs text-fail">
              lowercase letters, digits, <code>. _ -</code> only, starting with a letter or digit
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-service-display-name" className="text-xs font-medium text-fg-muted">
            Display name (optional)
          </label>
          <Input
            id="new-service-display-name"
            placeholder="Checkout API"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-service-kind" className="text-xs font-medium text-fg-muted">
            Kind
          </label>
          <Select
            id="new-service-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value as ComponentKind)}
          >
            {COMPONENT_KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-service-metrics" className="text-xs font-medium text-fg-muted">
            Monitored metrics, comma-separated (blank = score every metric seen)
          </label>
          <Input
            id="new-service-metrics"
            placeholder="http.server.duration, http.server.errors"
            value={metrics}
            onChange={(event) => setMetrics(event.target.value)}
          />
        </div>

        {existing.length > 0 ? (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-fg-muted">
              Depends on (declared as <code>http</code> connections, unclassified — change either below)
            </span>
            <div className="flex flex-wrap gap-3">
              {existing.map((component) => (
                <label key={component.id} className="flex items-center gap-1.5 text-xs text-fg">
                  <input
                    type="checkbox"
                    checked={dependsOn.includes(component.name)}
                    onChange={(event) =>
                      setDependsOn((current) =>
                        event.target.checked
                          ? [...current, component.name]
                          : current.filter((n) => n !== component.name),
                      )
                    }
                  />
                  {component.name}
                </label>
              ))}
            </div>
          </div>
        ) : null}

        {mutation.isError ? (
          <p className="font-mono text-xs text-fail">
            {mutation.error instanceof Error ? mutation.error.message : "Couldn't create component."}
          </p>
        ) : null}
        {failedConnections.length > 0 ? (
          <p className="font-mono text-xs text-fail">
            Created, but these connections were not: {failedConnections.join(", ")}. Add them
            below.
          </p>
        ) : null}

        <Button type="submit" size="sm" className="self-start" disabled={!nameValid || mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create component"}
        </Button>
      </form>

      {issuedKey ? (
        <NewKeyDialog
          serviceName={issuedKey.serviceName}
          apiKey={issuedKey.apiKey}
          onClose={() => setIssuedKey(null)}
        />
      ) : null}
    </>
  );
}

/** The typed edges out of one component (Phase 27 field 5: "connection
 * types visible"). The pre-Phase-27 page rendered this as a flat
 * `calls: a, b` line, which could not say whether the call was HTTP or
 * SQL, or whether it was on the request path — the two things the
 * diagnostic engine reasons about. */
function ConnectionsPanel({
  component,
  connections,
  components,
}: {
  component: ComponentOut;
  connections: ConnectionOut[];
  components: ComponentOut[];
}) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState("");
  const [kind, setKind] = useState<ConnectionKind>("http");
  const [criticality, setCriticality] = useState<Criticality>("unknown");

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["model"] });
  }

  const add = useMutation({
    mutationFn: () =>
      createConnection({
        from_component: component.name,
        to_component: target,
        kind,
        criticality,
        // A human declaring an edge here has the same provenance as one
        // written in culprit.yaml — a person wrote it down unprompted.
        // It is also the server's default; the
        // generated type requires it because the field has a default.
        declared_by: "culprit_yaml",
      }),
    onSuccess: () => {
      invalidate();
      setTarget("");
    },
  });

  const reclassify = useMutation({
    mutationFn: ({ id, next }: { id: string; next: Criticality }) =>
      patchConnection(id, { criticality: next }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteConnection(id),
    onSuccess: invalidate,
  });

  const candidates = components.filter((c) => c.name !== component.name);

  return (
    <div className="flex flex-col gap-2 rounded-md border border-line bg-surface-2 p-3">
      <span className="text-xs font-medium text-fg-muted">Connections</span>

      {connections.length === 0 ? (
        <p className="text-xs text-fg-muted">
          None declared. Nothing downstream of this component is on a request path yet.
        </p>
      ) : (
        <div className="flex flex-col gap-1">
          {connections.map((connection) => (
            <div
              key={connection.id}
              className="flex flex-col gap-2 border-t border-line pt-2 first:border-t-0 first:pt-0 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
                <span className="text-fg-muted">&rarr;</span>
                <span className="font-mono wrap-anywhere text-fg">{connection.to_component}</span>
                <Badge variant="default">{connection.kind}</Badge>
                <Badge
                  variant={connection.criticality === "on_request_path" ? "default" : "outline"}
                >
                  {CRITICALITY_LABEL[connection.criticality]}
                </Badge>
                {connection.declared_by !== "culprit_yaml" ? (
                  <span className="text-fg-muted">
                    {connection.declared_by === "accepted_suggestion" ? "accepted" : "inferred"}
                  </span>
                ) : null}
              </div>
              <div className="flex items-center gap-1">
                <Select
                  className="min-w-40"
                  aria-label={`Criticality of ${component.name} to ${connection.to_component}`}
                  value={connection.criticality}
                  onChange={(event) =>
                    reclassify.mutate({
                      id: connection.id,
                      next: event.target.value as Criticality,
                    })
                  }
                >
                  {CRITICALITIES.map((value) => (
                    <option key={value} value={value}>
                      {CRITICALITY_LABEL[value]}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => remove.mutate(connection.id)}
                  disabled={remove.isPending}
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {candidates.length > 0 ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (target) add.mutate();
          }}
        >
          <Select
            aria-label={`Add a connection from ${component.name}`}
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="">to…</option>
            {candidates.map((candidate) => (
              <option key={candidate.id} value={candidate.name}>
                {candidate.name}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Connection kind"
            value={kind}
            onChange={(event) => setKind(event.target.value as ConnectionKind)}
          >
            {CONNECTION_KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Connection criticality"
            value={criticality}
            onChange={(event) => setCriticality(event.target.value as Criticality)}
          >
            {CRITICALITIES.map((value) => (
              <option key={value} value={value}>
                {CRITICALITY_LABEL[value]}
              </option>
            ))}
          </Select>
          <Button type="submit" variant="secondary" size="sm" disabled={!target || add.isPending}>
            {add.isPending ? "Adding…" : "Add connection"}
          </Button>
        </form>
      ) : null}

      {add.isError ? (
        <p className="font-mono text-xs text-fail">
          {add.error instanceof Error ? add.error.message : "Couldn't add that connection."}
        </p>
      ) : null}
      {(reclassify.error ?? remove.error) ? (
        <p className="font-mono text-xs text-fail">
          {(reclassify.error ?? remove.error)?.message || "That change was not saved."}
        </p>
      ) : null}
    </div>
  );
}

function ComponentRow({
  component,
  connections,
  components,
}: {
  component: ComponentOut;
  connections: ConnectionOut[];
  components: ComponentOut[];
}) {
  const queryClient = useQueryClient();
  const [issuedKey, setIssuedKey] = useState<string | null>(null);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["model"] });
  }

  const setKind = useMutation({
    mutationFn: (next: ComponentKind) => patchComponent(component.id, { kind: next }),
    onSuccess: invalidate,
  });

  const toggleDisabled = useMutation({
    mutationFn: () => patchComponent(component.id, { disabled: !component.disabled }),
    onSuccess: invalidate,
  });

  const issueKey = useMutation({
    mutationFn: () => createKey(component.id, null),
    onSuccess: (result) => {
      invalidate();
      setIssuedKey(result.api_key);
    },
  });

  const revoke = useMutation({
    mutationFn: (keyId: string) => revokeKey(component.id, keyId),
    onSuccess: invalidate,
  });

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-line bg-surface-1 p-4 sm:p-5" data-testid="component-row">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-mono text-sm wrap-anywhere text-fg">{component.name}</span>
          {component.display_name ? (
            <span className="text-xs text-fg-muted">{component.display_name}</span>
          ) : null}
          {component.disabled ? <Badge variant="refused">disabled</Badge> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Phase 27: a component is a service, a database, a queue...
              and which one decides how it can be probed later. Editable
              here because the alternative is that everything migrated
              from the old registry stays labelled `service` forever. */}
          <Select
            aria-label={`Kind of ${component.name}`}
            value={component.kind}
            onChange={(event) => setKind.mutate(event.target.value as ComponentKind)}
            disabled={setKind.isPending}
          >
            {COMPONENT_KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => toggleDisabled.mutate()}
            disabled={toggleDisabled.isPending}
          >
            {component.disabled ? "Enable" : "Disable"}
          </Button>
        </div>
      </div>

      <ConnectionsPanel component={component} connections={connections} components={components} />
      <p className="text-xs text-fg-muted">
        monitored metrics:{" "}
        {component.monitored_metrics.length > 0 ? component.monitored_metrics.join(", ") : "all"}
      </p>

      <div className="flex flex-col gap-1">
        {component.keys.map((key) => (
          <div key={key.id} className="flex items-center justify-between gap-2 font-mono text-xs">
            <span className={key.revoked ? "text-fg-muted line-through" : "text-fg"}>
              {key.label ?? "(unlabeled)"}
              {/* Nullable at the database (a server default, no NOT
                  NULL), so the API says so — see KeyOut. */}
              {key.created_at ? ` · created ${formatDate(key.created_at)}` : ""}
              {key.last_used_at ? ` · last used ${formatDate(key.last_used_at)}` : ""}
            </span>
            {!key.revoked ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => revoke.mutate(key.id)}
                disabled={revoke.isPending}
              >
                Revoke
              </Button>
            ) : null}
          </div>
        ))}
      </div>

      <Button
        variant="secondary"
        size="sm"
        className="self-start"
        onClick={() => issueKey.mutate()}
        disabled={issueKey.isPending}
      >
        {issueKey.isPending ? "Issuing…" : "Issue new key"}
      </Button>

      {issuedKey ? (
        <NewKeyDialog serviceName={component.name} apiKey={issuedKey} onClose={() => setIssuedKey(null)} />
      ) : null}
      {(setKind.error ?? toggleDisabled.error ?? issueKey.error ?? revoke.error) ? (
        <p className="font-mono text-xs text-fail">
          {(setKind.error ?? toggleDisabled.error ?? issueKey.error ?? revoke.error)?.message || "That change was not saved."}
        </p>
      ) : null}
    </li>
  );
}

function TopologySuggestionRow({ suggestion }: { suggestion: TopologySuggestionOut }) {
  const accept = useAcceptTopologySuggestion();
  const dismiss = useDismissTopologySuggestion();
  const edge = { from_service: suggestion.from_service, to_service: suggestion.to_service };
  const bothRegistered = suggestion.from_service_registered && suggestion.to_service_registered;

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-line bg-surface-1 p-4 sm:p-5">
      <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
        <p className="font-mono text-sm wrap-anywhere text-fg">
          {suggestion.from_service} <span className="text-fg-muted">&rarr;</span>{" "}
          {suggestion.to_service}
        </p>
        <span className="text-xs text-fg-muted">
          seen {suggestion.observations} time
          {suggestion.observations === 1 ? "" : "s"} since{" "}
          {formatDate(suggestion.first_seen_at)}
        </span>
      </div>

      {!bothRegistered ? (
        <p className="text-xs text-fg-muted">
          {!suggestion.from_service_registered ? suggestion.from_service : suggestion.to_service}{" "}
          isn't a registered component yet — register it above before accepting this dependency.
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={!bothRegistered || accept.isPending}
          onClick={() => accept.mutate(edge)}
        >
          {accept.isPending ? "Accepting…" : "Accept"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate(edge)}
        >
          {dismiss.isPending ? "Dismissing…" : "Dismiss"}
        </Button>
      </div>
      {(accept.error ?? dismiss.error) ? (
        <p className="font-mono text-xs text-fail">
          {(accept.error ?? dismiss.error)?.message || "That suggestion was not updated."}
        </p>
      ) : null}
    </li>
  );
}

function TopologySuggestions() {
  const { suggestions, isPending, isError } = useTopologySuggestions();

  if (isPending || isError || suggestions.length === 0) return null;

  return (
    <section className="flex flex-col gap-3" aria-labelledby="suggestions-heading">
      <div>
        <h2 id="suggestions-heading" className="text-sm font-semibold text-fg">
          Suggested connections
        </h2>
        <p className="text-xs text-fg-muted">
          Observed in trace data, never applied by themselves — accepting one adds it to the system
          model as a connection; dismissing hides it and changes nothing.
        </p>
      </div>
      <ul className="flex flex-col gap-2">
        {suggestions.map((suggestion) => (
          <TopologySuggestionRow
            key={`${suggestion.from_service}->${suggestion.to_service}`}
            suggestion={suggestion}
          />
        ))}
      </ul>
    </section>
  );
}

export function SettingsServices() {
  // Phase 30: read entirely from /model. Until then the page listed via
  // the /services alias (which was the only shape carrying keys) and read
  // /model beside it for kinds and typed connections; ComponentOut now
  // carries keys itself, so there is one list and one query key to
  // invalidate.
  const { components, isPending, isError, error, refetch } = useComponents();
  const { connections } = useConnections();

  const outgoing = connectionsBySource(connections);

  return (
    <Page
      eyebrow="Settings"
      title="Services"
      description={
        <>
          The system model: each component, how it connects to the others, and the ingest keys its
          telemetry is sent with. <code className="font-mono text-code text-fg">culprit.yaml</code>{" "}
          applied with <code className="font-mono text-code whitespace-nowrap text-fg">just apply-model</code>{" "}
          writes the same records.
        </>
      }
    >
      <AddServiceForm existing={components} />

      {isPending ? <LoadingRows label="Loading components" rows={3} /> : null}
      {isError ? (
        <ErrorPanel
          title="Couldn't load components."
          message={error instanceof Error ? error.message : "The request failed."}
          onRetry={() => refetch()}
        />
      ) : null}

      {components.length > 0 ? (
        <ul className="flex flex-col gap-3" aria-label="Components">
          {components.map((component) => (
            <ComponentRow
              key={component.id}
              component={component}
              connections={outgoing.get(component.name) ?? []}
              components={components}
            />
          ))}
        </ul>
      ) : null}

      <TopologySuggestions />
    </Page>
  );
}
