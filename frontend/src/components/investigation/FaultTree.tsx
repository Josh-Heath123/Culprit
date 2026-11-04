import { ChevronRightIcon, CrosshairIcon, SignpostIcon, ZapIcon } from "lucide-react";
import { useId, useState } from "react";

import { Evidence } from "@/components/investigation/Evidence";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { TreeEdge } from "@/lib/types";

/** The fault tree from the symptom down, on a solid surface — glass never
 * goes on dense data. Every edge expands to the readings that established
 * it. The boundary is marked: the root when the walk finished, "walk
 * stopped here" when it did not (Phase 32.1 field 14). An edge whose
 * parent is not reachable from the symptom is shown as a start of its
 * own: the view never drops an established edge because it does not fit
 * the shape it expected. */
export function FaultTree({
  edges,
  symptom,
  boundary,
  complete,
}: {
  edges: TreeEdge[];
  symptom: string;
  boundary: string | null;
  complete: boolean;
}) {
  const edgesFrom = new Map<string, TreeEdge[]>();
  for (const edge of edges) {
    edgesFrom.set(edge.from_subject, [...(edgesFrom.get(edge.from_subject) ?? []), edge]);
  }
  const targets = new Set(edges.map((e) => e.to_subject));
  const starts = [symptom, ...[...edgesFrom.keys()].filter((s) => s !== symptom && !targets.has(s))];
  const context = { edgesFrom, symptom, boundary, complete };

  return (
    <Card aria-labelledby="tree-heading">
      <CardHeader
        id="tree-heading"
        title="Fault tree"
        trailing={
          edges.length > 0 ? (
            <span className="text-2xs text-fg-subtle">
              {edges.length} edge{edges.length === 1 ? "" : "s"}, each cited
            </span>
          ) : null
        }
      />
      <CardBody>
        {edges.length === 0 ? (
          <p className="text-sm text-fg-muted">
            No reading established an edge, so there is no tree to draw. The hypotheses below say what was
            tried.
          </p>
        ) : (
          <ul className="flex flex-col gap-1" data-testid="fault-tree">
            {starts.map((subject) => (
              <SubjectNode key={subject} subject={subject} context={context} seen={new Set()} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

interface Context {
  edgesFrom: Map<string, TreeEdge[]>;
  symptom: string;
  boundary: string | null;
  complete: boolean;
}

function SubjectNode({ subject, context, seen }: { subject: string; context: Context; seen: Set<string> }) {
  const next = new Set(seen).add(subject);
  const outgoing = seen.has(subject) ? [] : (context.edgesFrom.get(subject) ?? []);
  const isBoundary = subject === context.boundary;
  return (
    <li className="flex flex-col">
      <div
        className={cn(
          "flex flex-wrap items-center gap-2 self-start rounded-md border px-2.5 py-1.5",
          isBoundary && context.complete
            ? "border-highlight-line bg-highlight-tint"
            : isBoundary
              ? "border-inconclusive-line bg-inconclusive-tint"
              : "border-line bg-surface-2",
        )}
      >
        <span className="font-mono text-xs wrap-anywhere text-fg">{subject}</span>
        {subject === context.symptom ? (
          <span className="flex items-center gap-1 text-2xs font-medium text-fg-muted">
            <ZapIcon aria-hidden className="size-3" />
            symptom
          </span>
        ) : null}
        {isBoundary && context.complete ? (
          <span className="flex items-center gap-1 text-2xs font-semibold text-highlight" data-testid="root-marker">
            <CrosshairIcon aria-hidden className="size-3" />
            root
          </span>
        ) : null}
        {isBoundary && !context.complete ? (
          <span className="flex items-center gap-1 text-2xs font-semibold text-inconclusive" data-testid="stopped-marker">
            <SignpostIcon aria-hidden className="size-3" />
            walk stopped here
          </span>
        ) : null}
      </div>
      {outgoing.length > 0 ? (
        <ul className="ml-3 flex flex-col border-l border-line-strong pl-4">
          {outgoing.map((edge) => (
            <EdgeNode key={`${edge.from_subject}->${edge.to_subject}`} edge={edge} context={context} seen={next} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** In a partial diagnosis the boundary edge is where the walk stopped, not
 * a cause it established (Phase 32.1 field 14); the CLI's text output
 * labels it the same way. */
function relationLabel(edge: TreeEdge, complete: boolean): string {
  if (!complete && edge.relation === "caused_by") return "walk stopped at";
  return edge.relation.replaceAll("_", " ");
}

function EdgeNode({ edge, context, seen }: { edge: TreeEdge; context: Context; seen: Set<string> }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const count = edge.established_by.length;
  return (
    <li className="flex flex-col gap-1.5 pt-1.5">
      <button
        type="button"
        className="flex items-center gap-1.5 self-start rounded-sm py-1 text-xs text-fg-muted transition-colors duration-150 hover:text-fg"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panel}
        data-testid="edge-toggle"
      >
        <ChevronRightIcon
          aria-hidden
          className={cn("size-3.5 transition-transform duration-150", open && "rotate-90")}
        />
        <span className="font-medium text-fg">{relationLabel(edge, context.complete)}</span>
        <span>
          · {count} reading{count === 1 ? "" : "s"}
        </span>
      </button>
      {open ? (
        <div id={panel} className="pb-1">
          <Evidence readings={edge.readings} />
        </div>
      ) : null}
      <ul className="flex flex-col">
        <SubjectNode subject={edge.to_subject} context={context} seen={seen} />
      </ul>
    </li>
  );
}
