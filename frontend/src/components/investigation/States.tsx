import { CircleAlertIcon, FileSearchIcon, RotateCwIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** Loading, empty and error states for the investigation screens. Each
 * says what is happening in words; none of them is only a spinner. */

export function LoadingRows({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-busy="true" className="flex flex-col gap-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <Card key={index} className="flex flex-col gap-3 p-4 sm:p-5">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-16" />
          </div>
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </Card>
      ))}
    </div>
  );
}

export function LoadingInvestigation() {
  return (
    <div role="status" aria-busy="true" className="grid gap-4 lg:grid-cols-3">
      <span className="sr-only">Loading the investigation</span>
      <div className="flex flex-col gap-4 lg:col-span-2">
        <Card className="flex flex-col gap-3 p-5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-16 w-full" />
        </Card>
        <Card className="flex flex-col gap-3 p-5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-32 w-full" />
        </Card>
      </div>
      <Card className="flex flex-col gap-3 p-5">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-4 w-1/2" />
      </Card>
    </div>
  );
}

export function EmptyPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="flex flex-col items-center gap-3 px-6 py-12 text-center" data-testid="empty-state">
      <FileSearchIcon aria-hidden className="size-6 text-fg-subtle" />
      <h2 className="text-base font-semibold text-fg">{title}</h2>
      <div className="max-w-md text-sm leading-relaxed text-fg-muted">{children}</div>
    </Card>
  );
}

export function ErrorPanel({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <Card role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center" data-testid="error-state">
      <CircleAlertIcon aria-hidden className="size-6 text-fail" />
      <h2 className="text-base font-semibold text-fg">{title}</h2>
      <p className="max-w-md font-mono text-xs wrap-anywhere text-fg-muted">{message}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCwIcon aria-hidden />
          Try again
        </Button>
      ) : null}
    </Card>
  );
}
