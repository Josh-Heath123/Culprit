import { ChevronRightIcon, PlusIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/button";
import { EmptyPanel, ErrorPanel, LoadingRows } from "@/components/ui/states";
import { usePostmortems } from "@/hooks/usePostmortems";
import { formatDateTime } from "@/lib/datetime";

import { EmbeddingStatusBadge } from "./PostmortemEditor";

export function PostmortemList() {
  const { postmortems, isPending, isError, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    usePostmortems();

  return (
    <Page
      title="Postmortems"
      description="Written by your team. With a VOYAGE_API_KEY they are embedded, so a coding agent can search them through the MCP server before it changes something."
      actions={
        <Button asChild size="sm">
          <Link to="/postmortems/new">
            <PlusIcon aria-hidden />
            Write a postmortem
          </Link>
        </Button>
      }
    >
      {isPending ? <LoadingRows label="Loading postmortems" rows={3} /> : null}
      {isError ? (
        <ErrorPanel
          title="Couldn't load postmortems."
          message={error instanceof Error ? error.message : "The request failed."}
          onRetry={() => refetch()}
        />
      ) : null}
      {!isPending && !isError && postmortems.length === 0 ? (
        <EmptyPanel title="No postmortems yet">
          Write one with the button above, or from an incident in the history.
        </EmptyPanel>
      ) : null}

      {postmortems.length > 0 ? (
        <ul className="flex flex-col gap-2" aria-label="Postmortems">
          {postmortems.map((postmortem) => (
            <li key={postmortem.id}>
              <Link
                to={`/postmortems/${postmortem.id}`}
                className="group flex items-center gap-4 rounded-lg border border-line bg-surface-1 p-4 transition-colors duration-150 hover:border-line-strong hover:bg-surface-2 sm:p-5"
                data-testid="postmortem-row"
              >
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-fg">{postmortem.title}</span>
                    <EmbeddingStatusBadge status={postmortem.embedding_status} />
                  </div>
                  <p className="line-clamp-2 text-sm text-fg-muted">{postmortem.body}</p>
                  {postmortem.created_at ? (
                    <time dateTime={postmortem.created_at} className="text-2xs text-fg-subtle">
                      {formatDateTime(postmortem.created_at)}
                    </time>
                  ) : null}
                </div>
                <ChevronRightIcon
                  aria-hidden
                  className="size-4 shrink-0 text-fg-subtle transition-transform duration-150 group-hover:translate-x-0.5"
                />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

      {hasNextPage ? (
        <Button
          variant="outline"
          size="sm"
          className="self-center"
          onClick={() => void fetchNextPage()}
          disabled={isFetchingNextPage}
        >
          {isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      ) : null}
    </Page>
  );
}
