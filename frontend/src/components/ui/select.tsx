import * as React from "react";
import { ChevronDownIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** A native <select> on the design tokens. Native on purpose: keyboard,
 * screen-reader and mobile behaviour come from the platform, and no
 * listbox library is added (Phase 32.1 field 11). */
function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <span className={cn("relative inline-flex min-w-32", className)}>
      <select
        data-slot="select"
        className="h-9 w-full appearance-none rounded-md border border-line-strong bg-surface-2 py-0 pr-8 pl-3 text-sm text-fg disabled:cursor-not-allowed disabled:opacity-50"
        {...props}
      >
        {children}
      </select>
      <ChevronDownIcon
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-fg-subtle"
      />
    </span>
  );
}

export { Select };
