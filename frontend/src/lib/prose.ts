/** Splits prose that came from the walk or the API into text and
 * command-line flags, so a flag renders as code and never breaks across a
 * line (Phase 32.1 review: "(--reference)" wrapped as
 * "(--" / "reference)"). Pure, so it is unit-tested (lib/prose.test.ts);
 * components/ui/prose.tsx renders it. */
export type ProsePart = { kind: "text"; text: string } | { kind: "flag"; text: string };

/** `--reference`, `--from`, `--no-plugins`, `--fail-on=breaks_request_path`.
 * Two dashes, then a letter, so an em-dash-like "--" in prose or a range
 * like "8.2.0--8.2.2" is not a flag. */
const FLAG = /(?<![\w-])--[a-z][a-z0-9-]*(?:=[^\s,;)]*[^\s,;).])?/g;

export function splitFlags(text: string): ProsePart[] {
  const parts: ProsePart[] = [];
  let last = 0;
  for (const match of text.matchAll(FLAG)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ kind: "text", text: text.slice(last, start) });
    parts.push({ kind: "flag", text: match[0] });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", text: text.slice(last) });
  return parts;
}
