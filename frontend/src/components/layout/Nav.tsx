import { Link } from "react-router-dom";

interface NavProps {
  totalIncidents: number;
}

export function Nav({ totalIncidents }: NavProps) {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
      <div className="flex items-center gap-2">
        <Link to="/" className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-primary" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-foreground">Culprit</span>
        </Link>
        <span className="font-mono text-xs text-muted-foreground">
          {totalIncidents} incident{totalIncidents === 1 ? "" : "s"}
        </span>
      </div>
      <kbd className="rounded-sm border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
        ⌘K to jump
      </kbd>
    </header>
  );
}
