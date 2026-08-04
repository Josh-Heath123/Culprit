import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  heading?: string;
}

/** Same terse, specific voice as the empty state and the LLM
 * narratives — states what actually failed, not a generic "Something
 * went wrong." `heading` defaults to the whole-dashboard fetch failure
 * copy (its original, only use until now); pass a narrower one for a
 * scoped failure like a single incident fetch, so the copy doesn't
 * overclaim the whole API is unreachable when only one request failed. */
export function ErrorState({ message, onRetry, heading = "Couldn't reach the Culprit API." }: ErrorStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <p className="text-sm text-foreground">{heading}</p>
      <p className="max-w-md font-mono text-xs text-muted-foreground">{message}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
