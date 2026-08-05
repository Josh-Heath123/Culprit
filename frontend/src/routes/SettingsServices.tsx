import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useServices } from "@/hooks/useServices";
import { createKey, createService, patchService, revokeKey } from "@/lib/api";
import type { ServiceOut } from "@/lib/types";

const SERVICE_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]{0,62}$/;

/** Registered once, then never retrievable again (api/app/registry/schemas.py's
 * ServiceCreateResponse/KeyCreateResponse) — this modal is the only place a
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
      <DialogContent className="p-5">
        <div className="flex flex-col gap-3">
          <div>
            <p className="text-sm font-semibold text-foreground">New key for {serviceName}</p>
            <p className="mt-1 text-xs text-destructive">
              This is shown once. It cannot be retrieved again — copy it now.
            </p>
          </div>
          <code className="break-all rounded-md border border-border bg-secondary px-3 py-2 font-mono text-xs text-foreground">
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

function AddServiceForm({ existing }: { existing: ServiceOut[] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [metrics, setMetrics] = useState("");
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  const [issuedKey, setIssuedKey] = useState<{ serviceName: string; apiKey: string } | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createService({
        name,
        display_name: displayName.trim() || null,
        depends_on: dependsOn,
        monitored_metrics: metrics
          .split(",")
          .map((m) => m.trim())
          .filter(Boolean),
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
      setIssuedKey({ serviceName: result.service.name, apiKey: result.api_key });
      setName("");
      setDisplayName("");
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
        className="flex flex-col gap-3 rounded-md border border-border p-4"
      >
        <p className="text-sm font-semibold text-foreground">Register a service</p>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-service-name" className="text-xs font-medium text-muted-foreground">
            Name — must match the OTel <code>service.name</code> resource attribute exactly
          </label>
          <Input
            id="new-service-name"
            placeholder="checkout-api"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          {name && !nameValid ? (
            <p className="text-xs text-destructive">
              lowercase letters, digits, <code>. _ -</code> only, starting with a letter or digit
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="new-service-display-name" className="text-xs font-medium text-muted-foreground">
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
          <label htmlFor="new-service-metrics" className="text-xs font-medium text-muted-foreground">
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
            <span className="text-xs font-medium text-muted-foreground">Depends on</span>
            <div className="flex flex-wrap gap-3">
              {existing.map((service) => (
                <label key={service.id} className="flex items-center gap-1.5 text-xs text-foreground">
                  <input
                    type="checkbox"
                    checked={dependsOn.includes(service.name)}
                    onChange={(event) =>
                      setDependsOn((current) =>
                        event.target.checked
                          ? [...current, service.name]
                          : current.filter((n) => n !== service.name),
                      )
                    }
                  />
                  {service.name}
                </label>
              ))}
            </div>
          </div>
        ) : null}

        {mutation.isError ? (
          <p className="font-mono text-xs text-destructive">
            {mutation.error instanceof Error ? mutation.error.message : "Couldn't create service."}
          </p>
        ) : null}

        <Button type="submit" size="sm" className="self-start" disabled={!nameValid || mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create service"}
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

function ServiceRow({ service }: { service: ServiceOut }) {
  const queryClient = useQueryClient();
  const [issuedKey, setIssuedKey] = useState<string | null>(null);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["services"] });
  }

  const toggleDisabled = useMutation({
    mutationFn: () => patchService(service.id, { disabled: !service.disabled }),
    onSuccess: invalidate,
  });

  const issueKey = useMutation({
    mutationFn: () => createKey(service.id, null),
    onSuccess: (result) => {
      invalidate();
      setIssuedKey(result.api_key);
    },
  });

  const revoke = useMutation({
    mutationFn: (keyId: string) => revokeKey(service.id, keyId),
    onSuccess: invalidate,
  });

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm text-foreground">{service.name}</span>
          {service.display_name ? (
            <span className="text-xs text-muted-foreground">{service.display_name}</span>
          ) : null}
          {service.disabled ? <Badge variant="outline">disabled</Badge> : null}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => toggleDisabled.mutate()}
          disabled={toggleDisabled.isPending}
        >
          {service.disabled ? "Enable" : "Disable"}
        </Button>
      </div>

      {service.depends_on.length > 0 ? (
        <p className="text-xs text-muted-foreground">calls: {service.depends_on.join(", ")}</p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        monitored metrics:{" "}
        {service.monitored_metrics.length > 0 ? service.monitored_metrics.join(", ") : "all"}
      </p>

      <div className="flex flex-col gap-1">
        {service.keys.map((key) => (
          <div key={key.id} className="flex items-center justify-between gap-2 font-mono text-xs">
            <span className={key.revoked ? "text-muted-foreground line-through" : "text-foreground"}>
              {key.label ?? "(unlabeled)"} · created {new Date(key.created_at).toLocaleDateString()}
              {key.last_used_at ? ` · last used ${new Date(key.last_used_at).toLocaleDateString()}` : ""}
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
        <NewKeyDialog serviceName={service.name} apiKey={issuedKey} onClose={() => setIssuedKey(null)} />
      ) : null}
    </div>
  );
}

export function SettingsServices() {
  const { services, isPending, isError } = useServices();

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <span className="text-xs text-muted-foreground">/ Services</span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 overflow-y-auto p-6">
        <AddServiceForm existing={services} />

        {isPending ? <p className="text-xs text-muted-foreground">Loading services…</p> : null}
        {isError ? <p className="text-xs text-destructive">Couldn't load services.</p> : null}

        <div className="flex flex-col gap-3">
          {services.map((service) => (
            <ServiceRow key={service.id} service={service} />
          ))}
        </div>
      </main>
    </div>
  );
}
