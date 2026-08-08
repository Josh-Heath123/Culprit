import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useIncident } from "@/hooks/useIncident";
import {
  useCreatePostmortem,
  usePatchPostmortem,
  usePostmortem,
  useRetryPostmortemEmbedding,
} from "@/hooks/usePostmortems";
import { deletePostmortem } from "@/lib/api";
import type { EmbeddingStatus } from "@/lib/types";

/** Matches the eight fixture postmortems' own structure
 * (worker/app/rag/seed_postmortems.py) — retrieval quality depends on the
 * corpus having a consistent shape, so a new postmortem starts out
 * looking like the ones already grounding root-cause narratives. */
function bodySkeleton(): string {
  return "Summary: \n\nTimeline: \n\nRoot cause: \n\nResolution: \n";
}

function EmbeddingStatusBadge({
  status,
  error,
  onRetry,
  retrying,
}: {
  status: EmbeddingStatus;
  error: string | null;
  onRetry: () => void;
  retrying: boolean;
}) {
  if (status === "embedded") {
    return <Badge variant="outline">embedded</Badge>;
  }
  if (status === "pending") {
    return <Badge variant="outline">embedding…</Badge>;
  }
  return (
    <div className="flex items-center gap-2">
      <Badge variant="destructive">failed</Badge>
      <span className="max-w-md truncate font-mono text-xs text-destructive" title={error ?? ""}>
        {error}
      </span>
      <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
        {retrying ? "Retrying…" : "Retry"}
      </Button>
    </div>
  );
}

export function PostmortemEditor() {
  const navigate = useNavigate();
  const { postmortemId, incidentId } = useParams<{ postmortemId?: string; incidentId?: string }>();
  const isNew = postmortemId === undefined;

  const existing = usePostmortem(postmortemId);
  const incident = useIncident(isNew && incidentId ? incidentId : null);
  const createPostmortem = useCreatePostmortem();
  const patchPostmortem = usePatchPostmortem(postmortemId ?? "");
  const retryEmbedding = useRetryPostmortemEmbedding(postmortemId ?? "");

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Pre-fill exactly once, the moment the data it depends on arrives —
  // an existing postmortem's own title/body, or (for a brand-new one
  // opened from an incident) a skeleton naming that incident's services.
  useEffect(() => {
    if (initialized) return;
    if (!isNew && existing.data) {
      setTitle(existing.data.title);
      setBody(existing.data.body);
      setInitialized(true);
    } else if (isNew && incidentId) {
      if (!incident.data) return;
      setTitle(`Postmortem: ${incident.data.services.join(", ")}`);
      setBody(bodySkeleton());
      setInitialized(true);
    } else if (isNew && !incidentId) {
      setBody(bodySkeleton());
      setInitialized(true);
    }
  }, [initialized, isNew, existing.data, incident.data, incidentId]);

  const dirty = isNew || (existing.data && (title !== existing.data.title || body !== existing.data.body));
  const canSave = title.trim().length > 0 && body.trim().length > 0 && dirty;

  async function handleSave() {
    if (isNew) {
      const created = await createPostmortem.mutateAsync({
        title,
        body,
        incident_id: incidentId ?? null,
      });
      navigate(`/postmortems/${created.id}`, { replace: true });
    } else {
      await patchPostmortem.mutateAsync({ title, body });
    }
  }

  async function handleDelete() {
    if (!postmortemId) return;
    setDeleting(true);
    try {
      await deletePostmortem(postmortemId);
      navigate("/postmortems");
    } finally {
      setDeleting(false);
    }
  }

  const saving = createPostmortem.isPending || patchPostmortem.isPending;
  const saveError = createPostmortem.error ?? patchPostmortem.error;

  if (!isNew && existing.isPending) {
    return <p className="p-6 text-xs text-muted-foreground">Loading postmortem…</p>;
  }
  if (!isNew && existing.isError) {
    return <p className="p-6 text-xs text-destructive">Couldn't load this postmortem.</p>;
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <Link to="/postmortems" className="text-xs text-muted-foreground hover:text-foreground">
          / Postmortems
        </Link>
        <span className="text-xs text-muted-foreground">/ {isNew ? "New" : "Edit"}</span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 overflow-y-auto p-6">
        {incidentId ? (
          <p className="text-xs text-muted-foreground">
            Attached to{" "}
            <Link to={`/incidents/${incidentId}`} className="underline hover:text-foreground">
              this incident
            </Link>
            .
          </p>
        ) : null}

        {!isNew && existing.data ? (
          <div className="flex items-center justify-between">
            <EmbeddingStatusBadge
              status={existing.data.embedding_status}
              error={existing.data.embedding_error}
              onRetry={() => retryEmbedding.mutate()}
              retrying={retryEmbedding.isPending}
            />
            {existing.data.incident_id ? (
              <Link
                to={`/incidents/${existing.data.incident_id}`}
                className="text-xs text-muted-foreground underline hover:text-foreground"
              >
                view incident
              </Link>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <label htmlFor="postmortem-title" className="text-xs font-medium text-muted-foreground">
            Title
          </label>
          <Input
            id="postmortem-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Payments-service latency spike from a slow upstream call"
          />
        </div>

        <div className="flex flex-1 flex-col gap-1">
          <label htmlFor="postmortem-body" className="text-xs font-medium text-muted-foreground">
            Body — plain text, no rich formatting
          </label>
          <Textarea
            id="postmortem-body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={20}
            className="flex-1 resize-none font-mono"
          />
        </div>

        {saveError ? (
          <p className="font-mono text-xs text-destructive">
            {saveError instanceof Error ? saveError.message : "Couldn't save this postmortem."}
          </p>
        ) : null}

        <div className="flex items-center justify-between">
          <Button onClick={() => void handleSave()} disabled={!canSave || saving} size="sm">
            {saving ? "Saving…" : isNew ? "Create postmortem" : "Save"}
          </Button>
          {!isNew ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => void handleDelete()}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          ) : null}
        </div>
      </main>
    </div>
  );
}
