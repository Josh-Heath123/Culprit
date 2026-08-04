import { useEffect, useState } from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import type { IncidentSummary } from "@/lib/types";

interface CommandPaletteProps {
  incidents: IncidentSummary[];
  onSelectIncident: (id: string) => void;
}

/** Client-side only — fuzzy match over already-loaded incidents (id,
 * service name, hypothesis text), via cmdk's built-in scorer against
 * each item's `value`. No backend search endpoint: Phase 7 didn't build
 * one, and this dataset (a demo's worth of incidents) never approaches
 * the scale where client-side filtering would stop being "genuinely
 * sufficient." */
export function CommandPalette({ incidents, onSelectIncident }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  function select(id: string) {
    onSelectIncident(id);
    setOpen(false);
  }

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Jump to an incident by id, service, or hypothesis…" />
      <CommandList>
        <CommandEmpty>No matching incidents.</CommandEmpty>
        <CommandGroup heading={`Incidents (${incidents.length})`}>
          {incidents.map((incident) => {
            const searchValue = [
              incident.id,
              incident.services.join(" "),
              incident.root_cause_hypothesis ?? "",
            ]
              .join(" ")
              .toLowerCase();

            return (
              <CommandItem key={incident.id} value={searchValue} onSelect={() => select(incident.id)}>
                <span
                  className="mt-0.5 size-1.5 shrink-0 rounded-full"
                  style={{
                    background:
                      incident.root_cause_status === "ready" ? "var(--primary)" : "var(--severity-warning)",
                  }}
                />
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-sm text-foreground">
                      {incident.root_cause_hypothesis ?? "Narrative pending"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                    <span>{incident.id.slice(0, 8)}</span>
                    <span>·</span>
                    <span>{incident.services.join(", ")}</span>
                  </div>
                </div>
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
