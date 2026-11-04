import { Badge } from "@/components/ui/badge";
import type { InvestigationReading, Reading } from "@/lib/types";

/** The evidence for a fault edge: the readings it cites. Until Phase 32
 * this component rendered an LLM narrative's postmortem citations (now
 * incident-detail/NarrativeCitations.tsx, history); evidence is a probe's
 * reading now — what was measured, against what, under which grant.
 *
 * Every value shown here was redacted by POST /investigations before it was
 * stored (api/app/investigations/service.py), so nothing on this side needs
 * to decide what is safe to render. */
export function Evidence({ readings }: { readings: InvestigationReading[] }) {
  if (readings.length === 0) {
    return <p className="text-xs text-muted-foreground">No readings.</p>;
  }
  return (
    <ol className="flex flex-col gap-2" data-testid="edge-readings">
      {readings.map(({ id, reading }) => (
        <li key={id} className="flex flex-col gap-1 border-l-2 border-border pl-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[11px] text-muted-foreground">{id}</span>
            <VerdictBadge verdict={reading.verdict} />
            <span className="font-mono text-xs text-foreground">{reading.probe_id}</span>
          </div>
          <span className="font-mono text-[11px] text-muted-foreground">{reading.target}</span>
          {reading.reason ? <p className="text-xs text-foreground">{reading.reason}</p> : null}
          <Values label="measured" values={reading.measured} />
          {reading.expected ? <Values label="expected" values={reading.expected} /> : null}
          <span className="text-[11px] text-muted-foreground/70">
            {new Date(reading.taken_at).toLocaleString()} · {reading.agent_id}
            {reading.grants_used.length > 0 ? ` · grants: ${reading.grants_used.join(", ")}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function VerdictBadge({ verdict }: { verdict: Reading["verdict"] }) {
  const variant =
    verdict === "fail" ? "destructive" : verdict === "pass" ? "primary" : verdict === "refused" ? "warning" : "outline";
  return <Badge variant={variant}>{verdict}</Badge>;
}

function Values({ label, values }: { label: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-2 font-mono text-[11px]">
      <dt className="col-span-2 text-muted-foreground">{label}</dt>
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="pl-2 text-muted-foreground">{key}</dt>
          <dd className="break-all text-foreground">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
