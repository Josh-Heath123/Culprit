import { cn } from "@/lib/utils";

const STEP = 48;
const WIDTH = 2880;
const HEIGHT = 1920;
const MARK = 5;

/** The hairlines and the + marks, as two paths in user units (pixels): a
 * pattern fill would need a colour prop, which the token gate refuses. */
function grid(): { lines: string; marks: string } {
  const lines: string[] = [];
  const marks: string[] = [];
  for (let x = 0; x <= WIDTH; x += STEP) lines.push(`M${x + 0.5} 0V${HEIGHT}`);
  for (let y = 0; y <= HEIGHT; y += STEP) lines.push(`M0 ${y + 0.5}H${WIDTH}`);
  for (let x = 0; x <= WIDTH; x += STEP * 2) {
    for (let y = 0; y <= HEIGHT; y += STEP * 2) {
      marks.push(`M${x + 0.5 - MARK} ${y + 0.5}h${MARK * 2}M${x + 0.5} ${y + 0.5 - MARK}v${MARK * 2}`);
    }
  }
  return { lines: lines.join(""), marks: marks.join("") };
}

const GRID = grid();

/** The graticule (DELIVERY_PLAN I4): hairlines every 48 px with a + at
 * every other crossing, like an instrument's measuring grid — Culprit is a
 * multimeter for software. Faded toward the edges (index.css,
 * .graticule-fade). Decoration only, hidden from assistive technology,
 * and used on the expressive screens alone: sign-in, empty states, not
 * found. Never behind data. */
export function Graticule({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      focusable="false"
      className={cn("graticule-fade pointer-events-none absolute inset-0 size-full", className)}
      data-testid="graticule"
    >
      <path d={GRID.lines} className="fill-none stroke-graticule" />
      <path d={GRID.marks} className="fill-none stroke-graticule-mark" />
    </svg>
  );
}
