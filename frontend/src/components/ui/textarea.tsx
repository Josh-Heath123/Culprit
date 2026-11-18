import * as React from "react";

import { FIELD } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea data-slot="textarea" className={cn(FIELD, "w-full px-3 py-2", className)} {...props} />;
}

export { Textarea };
