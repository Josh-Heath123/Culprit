import { ChevronRightIcon, CrosshairIcon, SignpostIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { InvestigateThroughAgent } from "@/components/investigation/InvestigateThroughAgent";
import { Page } from "@/components/layout/Page";
import { EmptyPanel, ErrorPanel, LoadingRows } from "@/components/ui/states";
import { Badge } from "@/components/ui/badge";
import { DiagnosisBadge } from "@/components/ui/status";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useInvestigations } from "@/hooks/useInvestigations";
import type { InvestigationSummary } from "@/lib/types";
import { formatDateTime } from "@/lib/datetime";

/** Every stored investigation, newest first. They arrive from `culprit
 * diagnose` posted with the project token (README, "The control plane"), or
 * from an agent's walk — which an admin can start here (Phase 33 part 3). */
export function InvestigationList() {
  const { data, isPending, isError, error, refetch } = useInvestigations();
  const { data: me } = useCurrentUser();
  const items = data?.items ?? [];

  return (
    <Page
      title="Investigations"
      description={
        <>
          Each one is a <code className="font-mono text-code text-fg">culprit diagnose</code> run: a walk from a
          symptom down the request path, with every edge cited by the readings that established it.
        </>
      }
    >
      {me?.role === "admin" ? <InvestigateThroughAgent /> : null}

      {isPending ? <LoadingRows label="Loading investigations" /> : null}
      {isError ? (
        <ErrorPanel
          title="Couldn't load investigations."
          message={error instanceof Error ? error.message : "The request failed."}
          onRetry={() => refetch()}
        />
      ) : null}
      {!isPending && !isError && items.length === 0 ? (
        <EmptyPanel title="No investigations yet">
          Run <code className="font-mono text-xs text-fg">culprit diagnose</code> where the environment is and
          post its JSON to <code className="font-mono text-xs text-fg">POST /investigations</code>.{" "}
          <code className="font-mono text-xs text-fg">just quickstart</code> does both against the demo.
        </EmptyPanel>
      ) : null}

      {items.length > 0 ? (
        <section aria-labelledby="list-heading" className="flex flex-col gap-3">
          <h2 id="list-heading" className="text-2xs font-semibold tracking-widest text-fg-subtle uppercase">
            {items.length} investigation{items.length === 1 ? "" : "s"}, newest first
          </h2>
          <ul className="flex flex-col gap-2">
            {items.map((item) => (
              <li key={item.id}>
                <Row item={item} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Page>
  );
}

function Row({ item }: { item: InvestigationSummary }) {
  return (
    <Link
      to={`/investigations/${encodeURIComponent(item.id)}`}
      className="group flex items-center gap-4 rounded-lg border border-line bg-surface-1 p-4 transition-colors duration-150 hover:border-line-strong hover:bg-surface-2 sm:p-5"
      data-testid="investigation-row"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-2.5 lg:flex-row lg:items-center lg:gap-6">
        <div className="flex min-w-0 flex-col gap-1 lg:w-2/5">
          <span className="font-mono text-sm font-medium wrap-anywhere text-fg">{item.symptom_subject}</span>
          <span className="text-2xs text-fg-subtle">
            {item.environment} ·{" "}
            <time dateTime={item.opened_at}>{formatDateTime(item.opened_at)}</time>
          </span>
        </div>
        <Outcome item={item} />
        <div className="flex items-center gap-1.5 lg:ml-auto">
          <DiagnosisBadge complete={item.complete} />
          <Badge variant="outline">{item.attestation}</Badge>
        </div>
      </div>
      <ChevronRightIcon
        aria-hidden
        className="size-4 shrink-0 text-fg-subtle transition-transform duration-150 group-hover:translate-x-0.5"
      />
    </Link>
  );
}

/** A complete diagnosis names its root; a partial one names where the
 * walk stopped — never as "root" (Phase 32.1 field 14). */
function Outcome({ item }: { item: InvestigationSummary }) {
  if (item.root_subject === null) {
    return <span className="text-xs text-fg-muted lg:flex-1">No diagnosis reached</span>;
  }
  const complete = item.complete === true;
  return (
    <div className="flex min-w-0 flex-col gap-0.5 lg:flex-1" data-testid={complete ? "row-root" : "row-stopped"}>
      <span
        className={
          complete
            ? "flex items-center gap-1 text-2xs font-semibold tracking-widest text-highlight uppercase"
            : "flex items-center gap-1 text-2xs font-semibold tracking-widest text-inconclusive uppercase"
        }
      >
        {complete ? <CrosshairIcon aria-hidden className="size-3" /> : <SignpostIcon aria-hidden className="size-3" />}
        {complete ? "Root" : "Walk stopped at"}
      </span>
      <span className="font-mono text-xs wrap-anywhere text-fg">{item.root_subject}</span>
    </div>
  );
}
