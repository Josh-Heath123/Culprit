import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

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
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Client-side only — fuzzy match over already-loaded incidents (id,
 * service name, hypothesis text), via cmdk's built-in scorer against each
 * item's `value`. No backend search endpoint: a demo's worth of incidents
 * never approaches the scale where client-side filtering stops being
 * sufficient. Opened by Ctrl/⌘ K or the dashboard's button. */
export function CommandPalette({ incidents, open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  function select(id: string) {
    navigate(`/incidents/${id}`);
    onOpenChange(false);
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Jump to an incident">
      <CommandInput placeholder="Jump to an incident by id, service, or hypothesis…" />
      <CommandList>
        <CommandEmpty>No matching incidents.</CommandEmpty>
        <CommandGroup heading={`Incidents (${incidents.length})`}>
          {incidents.map((incident) => {
            const searchValue = [incident.id, incident.services.join(" "), incident.root_cause_hypothesis ?? ""]
              .join(" ")
              .toLowerCase();

            return (
              <CommandItem key={incident.id} value={searchValue} onSelect={() => select(incident.id)}>
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm text-fg">
                    {incident.root_cause_hypothesis ?? "No narrative (history)"}
                  </span>
                  <span className="flex items-center gap-1.5 font-mono text-2xs text-fg-muted">
                    <span>{incident.id.slice(0, 8)}</span>
                    <span aria-hidden>·</span>
                    <span>{incident.services.join(", ")}</span>
                  </span>
                </div>
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
