import { VerdictBadge } from "@/components/ui/status";
import type { InvestigationReading } from "@/lib/types";

/** The evidence for a fault edge: the readings it cites — what was
 * measured, against what, under which grant.
 *
 * Every value shown here was redacted by POST /investigations before it
 * was stored (api/app/investigations/service.py), so nothing on this side
 * decides what is safe to render. */
export function Evidence({ readings }: { readings: InvestigationReading[] }) {
  if (readings.length === 0) {
    return <p className="text-xs text-fg-muted">This edge cites no readings.</p>;
  }
  return (
    <ol className="flex flex-col gap-2" data-testid="edge-readings">
      {readings.map(({ id, reading }) => (
        <li key={id} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={reading.verdict} />
            <span className="font-mono text-xs font-medium wrap-anywhere text-fg">{reading.probe_id}</span>
            <span className="ml-auto font-mono text-2xs text-fg-subtle">{id}</span>
          </div>
          <span className="font-mono text-2xs wrap-anywhere text-fg-muted">{reading.target}</span>
          {reading.reason ? <p className="text-sm leading-relaxed text-fg">{reading.reason}</p> : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <Values label="Measured" values={reading.measured ?? {}} />
            {reading.expected ? <Values label="Expected" values={reading.expected} /> : null}
          </div>
          <p className="text-2xs text-fg-subtle">
            <time dateTime={reading.taken_at}>{new Date(reading.taken_at).toLocaleString()}</time> ·{" "}
            {reading.agent_id}
            {reading.grants_used.length > 0 ? ` · grants: ${reading.grants_used.join(", ")}` : ""}
          </p>
        </li>
      ))}
    </ol>
  );
}

function Values({ label, values }: { label: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  if (entries.length === 0) return null;
  return (
    <div className="min-w-0">
      <h4 className="mb-1 text-2xs font-semibold tracking-widest text-fg-subtle uppercase">{label}</h4>
      <dl className="flex flex-col gap-0.5 font-mono text-2xs">
        {entries.map(([key, value]) => (
          <div key={key} className="flex min-w-0 gap-2">
            <dt className="shrink-0 text-fg-muted">{key}</dt>
            <dd className="min-w-0 wrap-anywhere text-fg">{typeof value === "string" ? value : JSON.stringify(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
