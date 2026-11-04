import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { useInvestigations } from "@/hooks/useInvestigations";

/** Every stored investigation, newest first. They arrive from
 * `culprit diagnose` posted with the project token (README, "The control plane");
 * there is deliberately no button here that starts one. */
export function InvestigationList() {
  const { data, isPending, isError } = useInvestigations();
  const items = data?.items ?? [];

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <span className="text-xs text-muted-foreground">/ Investigations</span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3 overflow-y-auto p-6">
        {isPending ? <p className="text-xs text-muted-foreground">Loading investigations…</p> : null}
        {isError ? <p className="text-xs text-destructive">Couldn't load investigations.</p> : null}
        {!isPending && !isError && items.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No investigations yet. Run <code className="font-mono">culprit diagnose</code> where the
            environment is, and post its JSON to <code className="font-mono">POST /investigations</code>{" "}
            — <code className="font-mono">just quickstart</code> does both against the demo.
          </p>
        ) : null}

        {items.map((item) => (
          <Link
            key={item.id}
            to={`/investigations/${encodeURIComponent(item.id)}`}
            className="flex flex-col gap-1.5 rounded-md border border-border p-4 hover:border-foreground/30"
            data-testid="investigation-row"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-foreground">{item.symptom_subject}</span>
              <div className="flex items-center gap-1.5">
                <Badge variant="outline">{item.attestation}</Badge>
                {item.complete === null ? (
                  <Badge variant="outline">no diagnosis</Badge>
                ) : (
                  <Badge variant={item.complete ? "primary" : "warning"}>
                    {item.complete ? "complete" : "partial"}
                  </Badge>
                )}
              </div>
            </div>
            <span className="font-mono text-[11px] text-muted-foreground">
              root: {item.root_subject ?? "—"}
            </span>
            <span className="text-[11px] text-muted-foreground/70">
              {item.environment} · {new Date(item.opened_at).toLocaleString()}
            </span>
          </Link>
        ))}
      </main>
    </div>
  );
}
