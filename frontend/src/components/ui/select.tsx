// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

import * as React from "react";
import { ChevronDownIcon } from "lucide-react";

import { FIELD } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** A native <select> on the design tokens, styled as every other field.
 * Native on purpose: keyboard, screen-reader and mobile behaviour come
 * from the platform, and no listbox library is added (Phase 32.1 field
 * 11). */
function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <span className={cn("relative inline-flex min-w-32", className)}>
      <select
        data-slot="select"
        className={cn(FIELD, "h-9 w-full appearance-none py-0 pr-8 pl-3")}
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
