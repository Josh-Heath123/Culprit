import * as React from "react";

import { cn } from "@/lib/utils";

/** A text field: a well (surface-sunken) inside a 3:1 boundary
 * (line-strong), the subtle placeholder; the same as Textarea and
 * Select, so every field on every screen looks alike. */
export const FIELD =
  "rounded-md border border-line-strong bg-surface-sunken text-sm text-fg placeholder:text-fg-subtle transition-colors duration-150 ease-out hover:border-fg-subtle disabled:cursor-not-allowed disabled:opacity-50";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return <input type={type} data-slot="input" className={cn(FIELD, "h-9 w-full px-3", className)} {...props} />;
}

export { Input };
