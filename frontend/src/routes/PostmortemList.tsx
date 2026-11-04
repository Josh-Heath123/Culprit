import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePostmortems } from "@/hooks/usePostmortems";
import type { EmbeddingStatus } from "@/lib/types";

function statusBadgeVariant(status: EmbeddingStatus): "outline" | "destructive" {
  return status === "failed" ? "destructive" : "outline";
}

export function PostmortemList() {
  const { postmortems, isPending, isError, hasNextPage, fetchNextPage, isFetchingNextPage } =
    usePostmortems();

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="size-2 rounded-full bg-primary" aria-hidden />
            <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
          </Link>
          <span className="text-xs text-muted-foreground">/ Postmortems</span>
        </div>
        <Button asChild size="sm">
          <Link to="/postmortems/new">Write a postmortem</Link>
        </Button>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3 overflow-y-auto p-6">
        {isPending ? <p className="text-xs text-muted-foreground">Loading postmortems…</p> : null}
        {isError ? <p className="text-xs text-destructive">Couldn't load postmortems.</p> : null}
        {!isPending && postmortems.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Nothing here yet. Postmortems your team writes are kept here and, with a
            VOYAGE_API_KEY, embedded so a coding agent can search them through the MCP server.
          </p>
        ) : null}

        {postmortems.map((postmortem) => (
          <Link
            key={postmortem.id}
            to={`/postmortems/${postmortem.id}`}
            className="flex flex-col gap-1.5 rounded-md border border-border p-4 hover:border-foreground/30"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-foreground">{postmortem.title}</span>
              <Badge variant={statusBadgeVariant(postmortem.embedding_status)}>
                {postmortem.embedding_status}
              </Badge>
            </div>
            <p className="line-clamp-2 text-xs text-muted-foreground">{postmortem.body}</p>
            {postmortem.created_at ? (
              <span className="text-[11px] text-muted-foreground/70">
                {new Date(postmortem.created_at).toLocaleString()}
              </span>
            ) : null}
          </Link>
        ))}

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
      </main>
    </div>
  );
}
