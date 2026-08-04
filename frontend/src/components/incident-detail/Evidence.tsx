import type { CitedEvidenceOut } from "@/lib/types";

/** Displayed visibly as footnotes, per Section 3's voice charter: "cite
 * the specific retrieved postmortem passage... visibly, like a
 * footnote — this makes the suggestion auditable instead of a
 * 'trust me' black box." Never just the hypothesis text alone. */
export function Evidence({ evidence }: { evidence: CitedEvidenceOut[] }) {
  if (evidence.length === 0) {
    return <p className="text-xs text-muted-foreground">No cited evidence.</p>;
  }

  return (
    <ol className="flex flex-col gap-3">
      {evidence.map((item, index) => (
        <li key={`${item.postmortem_title}-${index}`} className="border-l-2 border-border pl-3">
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-xs text-muted-foreground">[{index + 1}]</span>
            <span className="text-xs font-medium text-foreground">{item.postmortem_title}</span>
          </div>
          <blockquote className="mt-1 text-xs text-muted-foreground italic">
            &ldquo;{item.passage}&rdquo;
          </blockquote>
        </li>
      ))}
    </ol>
  );
}
