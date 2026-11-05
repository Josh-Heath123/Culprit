import { splitFlags } from "@/lib/prose";

/** Text from the walk or the API, with every command-line flag in it
 * rendered as code that never breaks across a line (`--reference`). Use it
 * for any statement, reason or caption that is data rather than copy. */
export function Prose({ text }: { text: string }) {
  return (
    <>
      {splitFlags(text).map((part, index) =>
        part.kind === "flag" ? (
          <code key={index} className="font-mono text-code whitespace-nowrap text-fg">
            {part.text}
          </code>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </>
  );
}
