// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

import { CircleAlertIcon, CircleCheckIcon, FileSearchIcon, RotateCwIcon } from "lucide-react";

import { Graticule } from "@/components/layout/Graticule";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Loading, empty, error and success states. Each says what is happening
 * in words; none of them is only a spinner. Empty is an expressive screen
 * (the graticule, I4); loading and error are quiet. */

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
          <Skeleton className="h-8 w-2/3" />
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
    <Card
      className="relative isolate flex flex-col items-center gap-3 overflow-hidden px-6 py-14 text-center"
      data-testid="empty-state"
    >
      <Graticule className="-z-10" />
      <FileSearchIcon aria-hidden className="size-6 text-fg-subtle" />
      <h2 className="text-base font-semibold tracking-tight text-fg">{title}</h2>
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

/** One way to say that an action failed, on every screen: the fail tone,
 * an icon and the words, announced (role="alert"). */
export function ErrorNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p role="alert" className={cn("flex items-start gap-1.5 text-xs leading-relaxed text-fail", className)}>
      <CircleAlertIcon aria-hidden className="mt-px size-3.5 shrink-0" />
      <span className="min-w-0 wrap-anywhere">{children}</span>
    </p>
  );
}

/** One way to say that an action succeeded: the pass tone, an icon and the
 * words, announced politely. */
export function SuccessNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p role="status" className={cn("flex items-start gap-1.5 text-xs leading-relaxed text-pass", className)}>
      <CircleCheckIcon aria-hidden className="mt-px size-3.5 shrink-0" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}
