import { Link } from "react-router-dom";

import type { CitedEvidenceOut } from "@/lib/types";

/** Displayed visibly as footnotes, per Section 3's voice charter: "cite
 * the specific retrieved postmortem passage... visibly, like a
 * footnote — this makes the suggestion auditable instead of a
 * 'trust me' black box." Never just the hypothesis text alone. */
export function NarrativeCitations({ evidence }: { evidence: CitedEvidenceOut[] }) {
  if (evidence.length === 0) {
    return <p className="text-xs text-fg-muted">No cited evidence.</p>;
  }

  return (
    <ol className="flex flex-col gap-3">
      {evidence.map((item, index) => (
        <li key={`${item.postmortem_title}-${index}`} className="border-l-2 border-line pl-3">
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-xs text-fg-muted">[{index + 1}]</span>
            {/* root_cause_evidence is a JSONB snapshot (api/app/db/models.py's
             * IncidentCandidate docstring), so the title/passage text survives
             * a deleted postmortem regardless — only this link can go stale,
             * and PostmortemEditor's own 404 state (existing.isError) is what
             * "degrade gracefully" means here, not anything special on this
             * side. postmortem_id can also be null if the narrative cited a
             * title that didn't match any retrieved postmortem at generation
             * time (worker/app/rag/job.py) — plain text in that case. */}
            {item.postmortem_id ? (
              <Link
                to={`/postmortems/${item.postmortem_id}`}
                className="text-xs font-medium text-fg underline-offset-2 hover:text-brand hover:underline"
              >
                {item.postmortem_title}
              </Link>
            ) : (
              <span className="text-xs font-medium text-fg">{item.postmortem_title}</span>
            )}
          </div>
          <blockquote className="mt-1 text-xs text-fg-muted italic">
            &ldquo;{item.passage}&rdquo;
          </blockquote>
        </li>
      ))}
    </ol>
  );
}
