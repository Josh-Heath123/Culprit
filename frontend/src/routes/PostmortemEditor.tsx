import { useEffect, useState } from "react";
import { CircleCheckIcon, CircleXIcon, LoaderIcon } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Page } from "@/components/layout/Page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorPanel, LoadingRows } from "@/components/ui/states";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useIncident } from "@/hooks/useIncident";
import {
  useCreatePostmortem,
  useDeletePostmortem,
  usePatchPostmortem,
  usePostmortem,
  useRetryPostmortemEmbedding,
} from "@/hooks/usePostmortems";
import type { EmbeddingStatus } from "@/lib/types";

/** Matches the eight fixture postmortems' own structure
 * (worker/scripts/seed_postmortems.py), so search over the corpus sees one
 * consistent shape. */
function bodySkeleton(): string {
  return "Summary: \n\nTimeline: \n\nRoot cause: \n\nResolution: \n";
}

/** Whether a postmortem is embedded for search: a word and an icon, never
 * colour alone. */
export function EmbeddingStatusBadge({ status }: { status: EmbeddingStatus }) {
  if (status === "embedded") {
    return (
      <Badge variant="outline">
        <CircleCheckIcon aria-hidden className="size-3" />
        embedded
      </Badge>
    );
  }
  if (status === "pending") {
    return (
      <Badge variant="unknown">
        <LoaderIcon aria-hidden className="size-3" />
        embedding…
      </Badge>
    );
  }
  return (
    <Badge variant="fail">
      <CircleXIcon aria-hidden className="size-3" />
      embedding failed
    </Badge>
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
  // The hook, not a bare deletePostmortem() call: it invalidates the
  // ["postmortems"] list, without which the list a successful delete
  // navigates to still showed the postmortem just deleted (Phase 31.2
  // truth pass).
  const deletePostmortem = useDeletePostmortem();

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

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
    try {
      await deletePostmortem.mutateAsync(postmortemId);
    } catch {
      return; // shown below from deletePostmortem.error
    }
    navigate("/postmortems");
  }

  const saving = createPostmortem.isPending || patchPostmortem.isPending;
  const saveError = createPostmortem.error ?? patchPostmortem.error;
  const deleteError = deletePostmortem.error;
  const deleting = deletePostmortem.isPending;

  if (!isNew && existing.isPending) {
    return (
      <Page title="Postmortem">
        <LoadingRows label="Loading the postmortem" rows={1} />
      </Page>
    );
  }
  if (!isNew && existing.isError) {
    return (
      <Page title="Postmortem">
        <ErrorPanel
          title="Couldn't load this postmortem."
          message={existing.error instanceof Error ? existing.error.message : "The request failed."}
          onRetry={() => existing.refetch()}
        />
      </Page>
    );
  }

  return (
    <Page
      eyebrow={
        <Link to="/postmortems" className="hover:text-fg">
          Postmortems
        </Link>
      }
      title={isNew ? "Write a postmortem" : "Edit postmortem"}
      description={
        incidentId || existing.data?.incident_id ? (
          <>
            Attached to{" "}
            <Link
              to={`/incidents/${incidentId ?? existing.data?.incident_id}`}
              className="text-brand underline-offset-2 hover:underline"
            >
              an incident
            </Link>{" "}
            (history).
          </>
        ) : undefined
      }
    >
      <Card className="flex flex-col gap-5 p-4 sm:p-6">
        {!isNew && existing.data ? (
          <div className="flex flex-wrap items-center gap-2">
            <EmbeddingStatusBadge status={existing.data.embedding_status} />
            {existing.data.embedding_status === "failed" ? (
              <>
                {existing.data.embedding_error ? (
                  <span className="min-w-0 font-mono text-xs wrap-anywhere text-fail">
                    {existing.data.embedding_error}
                  </span>
                ) : null}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => retryEmbedding.mutate()}
                  disabled={retryEmbedding.isPending}
                >
                  {retryEmbedding.isPending ? "Retrying…" : "Retry embedding"}
                </Button>
              </>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <label htmlFor="postmortem-title" className="text-xs font-medium text-fg-muted">
            Title
          </label>
          <Input
            id="postmortem-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Payments-service latency spike from a slow upstream call"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="postmortem-body" className="text-xs font-medium text-fg-muted">
            Body — plain text, no rich formatting
          </label>
          <Textarea
            id="postmortem-body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={18}
            className="resize-y font-mono"
          />
        </div>

        {saveError ? (
          <p role="alert" className="rounded-md border border-fail-line bg-fail-tint px-3 py-2 text-xs text-fail">
            {saveError instanceof Error ? saveError.message : "Couldn't save this postmortem."}
          </p>
        ) : null}
        {deleteError ? (
          <p role="alert" className="rounded-md border border-fail-line bg-fail-tint px-3 py-2 text-xs text-fail">
            {deleteError instanceof Error ? deleteError.message : "Couldn't delete this postmortem."}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button onClick={() => void handleSave()} disabled={!canSave || saving}>
            {saving ? "Saving…" : isNew ? "Create postmortem" : "Save"}
          </Button>
          {!isNew ? (
            confirmingDelete ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-fg-muted">Delete it for good?</span>
                <Button variant="outline" size="sm" onClick={() => setConfirmingDelete(false)}>
                  Keep
                </Button>
                <Button variant="destructive" size="sm" onClick={() => void handleDelete()} disabled={deleting}>
                  {deleting ? "Deleting…" : "Delete"}
                </Button>
              </div>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(true)}>
                Delete…
              </Button>
            )
          ) : null}
        </div>
      </Card>
    </Page>
  );
}
