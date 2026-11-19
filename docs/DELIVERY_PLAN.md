# Culprit — delivery plan: Phases 40–43

Written 2026-11-18 by the architecture session, and added in the review that
signs off Phase 39 (`33df658`). It is the plan of record after
`docs/PERFORMANCE_PLAN.md`. `docs/DIAGNOSTIC_PLAN.md`'s D1–D8 and standing
invariants, and the performance plan's P1–P8, still bind. Nothing here changes
what Culprit diagnoses, except C1, carried from Phase 39, which changes the
demo's N+1 route.

It answers four requests the owner made on 2026-11-18, in this order:
1. **A new visual identity.** The dashboard and the repository take a new
   look, from the owner's reference image: deep plum, electric violet and
   acid lime, with Apple-like restraint and glass used selectively.
2. **A repository that presents the work at its true value,** with the
   least effort for someone who has never seen it.
3. **Pipelines that make every merge correct, fast.**
4. **Ownership, and authentication, on the record.**

Deploy stays paused (owner, 2026-11-05). Nothing here deploys, cuts a
release, or makes the ghcr.io packages public. Publication still waits for
a confirmed outside finding.

---

## §1. Where things stand (measured on `33df658`, 2026-11-18)

**The dashboard** (`frontend/`; React 18, Tailwind 4, fontsource Inter and
JetBrains Mono, `tw-animate-css`):
- **Routes:** login; the investigations list and view; incidents and
  postmortems; three admin settings pages; not-found.
- **Components:** 47 `.tsx` files, including the investigation's diagnosis,
  fault tree, evidence, hypotheses, verifications and narration panels.
- **Today's design system** is `frontend/src/index.css`, from
  PRODUCTISATION §2: midnight surfaces, a blue accent, a cantaloupe
  highlight, and verdict and severity colours.
  - Glass is already reserved for layered elements (navigation, dialogs,
    popovers), never tables or the fault tree.
  - A reduced-motion rule exists.
- **The token rules are enforced:**
  - `check-frontend-tokens`: no page styles itself outside the tokens.
  - `scripts/tests/test_design_tokens.py`: every text token's contrast on
    every surface.
  - e2e: every route at 375, 768, 1280 and 1920 px. It also takes the
    README's screenshots.
- **The mark** (`Brand.tsx`) is a cantaloupe dot beside the name. The
  favicon is Vite's default logo.

**The repository's presentation:**
- **`README.md` is 1,021 lines,** about 490 of them an end-to-end tutorial.
- **Its strengths are worth keeping:** a sharp, true problem statement;
  terminal captures regenerated from real runs by `just readme-captures`
  (in GitHub's palette, not the product's); screenshots from e2e; and an
  accuracy section generated from the fault library.
- **It contradicts the code in places:**
  - "Thirteen read-only probes" in one place, "seventeen" in another, and
    eighteen in the catalogue;
  - "Future work" lists Phases 36–39, all of which are now done.
- **The performance work appears only inside the tutorial:** budgets
  judged with a confidence interval, plan-derived index recommendations,
  bundle and list bounds, and N+1.

**CI:**
- **The critical path is lint → cli → fault-library: 18 to 23 minutes**
  (23.0 and 23.2 on the last two pull-request runs, 44321940704 and
  44313908008). The fault library waits on `cli` without using anything
  it produces.
- **The N+1 case's headroom is 2.6 ms on the fastest runner seen**, under the
  20 ms budget Q40 set (Phase 39's review). C1, carried into Phase 40 part 1,
  is the remedy.
- `main`'s ruleset (26460341) requires **no** status checks, and the owner
  merges under a bypass. PR #48 was merged while its last commit's run was
  still in progress.

**Ownership:**
- `LICENSING.md` and the README name Joshua Heath. Of `main`'s 286
  commits, 233 are authored as `Josh-Heath123` and 53 as Joshua Heath,
  from the same person's addresses (one is a university address).
- There are no SPDX headers, and no NOTICE, contributor agreement, trademark
  policy, citation file or vulnerability policy.

---

## §2. The identity (decided 2026-11-18)

**I1. A new identity replaces PRODUCTISATION §2's palette, by the owner's
decision.**
- The owner's reference image (a design whose palette is deep plum,
  electric violet and acid lime) is the source. That image is someone
  else's work and is not committed: this plan records its colours and
  ideas, not the image.
- PRODUCTISATION §2's other principles stand: selective glass, consistency,
  accessibility, and colour with a purpose.

**I2. The anchors, and what each one is for.**

| Role | Value | Contrast, measured |
|---|---|---|
| The page | **Deep Plum `#221331`** | cream text on it 17.1:1 |
| Text | Cream `#FDFDFD`, with muted and subtle steps derived from it | — |
| Brand and interaction: primary fills, focus rings, selection | **Electric Violet `#7540F5`** | cream on violet 5.4:1; violet on plum 3.2:1 |
| **The culprit** | **Acid Lime `#D6FA4A`** | lime on plum 14.6:1; lime on cream 1.2:1 |

- **Surfaces** are derived from plum by lightness alone: one step darker
  for wells and tables, and steps lighter for raised panels.
- **Violet is never body text on plum,** because 3.2:1 is under 4.5:1.
  Links and violet text use a lighter tint that clears 4.5:1. `#7540F5`
  itself is for fills, rings and selection, where 3:1 is the bar.
- **Lime has one meaning: the answer.**
  - It marks the walk's root, the diagnosis line, and on the README the
    one generated figure that matters (the accuracy).
  - It is never a button colour, a link or decoration.
  - Text on lime is plum.
  - On cream, lime appears only as a filled block with plum text (1.2:1
    otherwise).
- **Verdict and severity colours are re-derived** so none can be mistaken
  for lime or violet:
  - pass is a teal-green, well away from lime's hue of 72°;
  - fail and `breaks` are coral-red;
  - inconclusive moves off violet to a sky blue;
  - `degrades` moves off yellow to orange;
  - refused and cosmetic are plum-greys.

  Every verdict keeps its word beside its colour.

**I3. Type.**
- **Inter** for everything read, with a display weight added for editorial
  headings: 700, from the fontsource package already installed. Headings
  use tight tracking and a restrained scale.
- **JetBrains Mono, upper-case and letter-spaced, at small sizes** for
  labels, identifiers and metadata. This is the reference's technical
  voice, and Culprit's subjects and probe IDs are already mono.
- **The large, editorial moment on a screen is its answer.** On the
  investigation page that is the diagnosis's root statement; on a list, the
  page title. Nothing else competes with it.

**I4. Motifs, used sparingly.**
- **A graticule:** hairline grid lines with `+` marks at their crossings,
  like an instrument's measuring grid. Culprit is "a multimeter for
  software". It appears on the login page, empty states, not-found, and the
  README's hero; never behind data.
- **A lime outline glow** marks the culprit: the root node of the fault
  tree.
- **A violet radial glow** appears on the login page and the README's hero
  only.

**I5. Glass where layering helps, never where reading matters.**
Navigation, the command palette, dialogs, popovers and tooltips use frosted
plum glass (a translucent surface, background blur, a hairline highlight).
Tables, the fault tree, evidence, forms and settings stay solid.

**I6. Motion with a purpose.**
- 150–220 ms ease-out transitions on hover, press, selection, expanding
  fault-tree edges, and opening dialogs and popovers.
- Nothing animates data.
- The existing reduced-motion rule turns all of it off.

**I7. Restraint is checked.**
- **The lime token is named for its role (`--culprit`).**
  `check-frontend-tokens` allows it only in the components declared to mark
  the answer.
- **Glass tokens are likewise allowed only in the declared layered
  components.**
- **`test_design_tokens.py` gains a hue-separation test:** lime and violet
  against every verdict and severity colour.
- A mutation of each is shown red.

---

## §3. Decisions for the repository and the pipelines

**S1. Every picture is a real run.**
- The terminal captures are re-themed to I2's tokens in
  `scripts/render_captures.py` (one constant block), and regenerated by
  `just readme-captures`.
- The dashboard screenshots are retaken by e2e after the redesign.
- **One capture is added if it renders from a recorded walk:** `culprit
  diagnose` naming a root. If it cannot be rendered from a real record, it
  is not drawn.
- No video link until the video exists.

**S2. The hero is rendered, not drawn by hand.**
- `docs/brand/hero.html` is the source. Playwright, which e2e already uses,
  renders it with the fontsource fonts into `hero-dark.png` and
  `hero-light.png` (3200×800, shown at half size through `<picture>` for
  GitHub's two themes) and `social-preview.png` (1280×640).
- The hero has the plum field, the violet glow and the graticule; the
  wordmark, large, with the lime mark; and the promise in mono capitals. It
  also carries one lime figure: the accuracy, **read from the fault
  library's generated results at render time**, never typed.
- The light variant is cream, with plum text and violet accents. Its lime
  appears only as a filled block.
- No new dependency.

**S3. The README is the overview; depth has a home.**
- **Under 300 lines,** in the order a newcomer asks:
  1. the hero, and one line of links;
  2. the problem;
  3. see it work;
  4. what it does, in six to eight one-sentence rows, budgets among them;
  5. how it works: the three planes, a Mermaid diagram of **the walk**, and
     why no model decides;
  6. engineering highlights, each naming the file or test that holds it;
  7. accuracy, the generated block;
  8. quickstart;
  9. status: done, in progress, planned;
  10. the documentation map;
  11. technology; author and licence.
- **The Mermaid diagrams take I2's colours** through an `init` block, and
  the root node is lime by a `classDef`.
- **The tutorial moves verbatim to `docs/GUIDE.md`.** Nothing is deleted
  without a home.
- No shields.io badges and no emoji. GitHub's own CI badge is allowed once
  Phase 41's gate is required.

**S4. Truth is checked.**
- `scripts/check_readme.py` (standard library only) joins `lint`. It checks:
  - every relative link and image in `README.md` and `docs/*.md` resolves;
  - the README's probe count equals the catalogue;
  - every self-check figure the README quotes equals the self-check's
    output.
- Each check's mutation is shown red. Everything else is audited by hand,
  and listed in the report.

**D1. One required check, `gate`.** It needs every job and fails unless
each succeeded. Jobs skipped by design (`publish`, `deploy` on a pull
request) are listed by name. The ruleset requires `gate` alone, and strict.

**D2. What is tested is what lands.** Strict checks require an up-to-date
branch. A merge queue needs an organisation-owned repository, which is not
proposed.

**D3. No bypass.** `main` changes only through a pull request whose `gate`
passed.

**D4. Speed is measured.** Target: a critical path of 12 minutes or less.
The means, each kept only if two runs show the gain:
- the fault library after `lint`, not `cli`;
- four shards, held by the shard test;
- Docker layer caching;
- the database boundary as its own job;
- `concurrency:` on pull requests.

**D5. No gate is weakened for speed.** No path filter skips a code job,
nothing is retried, and no test or precondition is loosened.

**D6. A flaky required check is a defect**, to be attributed (Q37–Q40).

**D7. Authenticated:**
- signed commits required on `main`;
- third-party actions pinned to SHAs, with Dependabot;
- artifact attestations on published images and CLI binaries, verified in
  the workflow.

**D8. Ownership on the record:**
- SPDX/REUSE headers on every file, held by `reuse lint`;
- NOTICE;
- `AUTHORSHIP.md`, stating facts with pointers to their evidence;
- `CONTRIBUTING.md` with a CLA from a recognised template, to be read by a
  lawyer before an outside contribution is accepted;
- `TRADEMARKS.md`, `CITATION.cff` and `SECURITY.md`;
- a Software Heritage archive, which is a human step.

**D9. Human steps are the owner's,** and are named at each review.

---

## Phase 40 — The new identity

**Goal.** The dashboard and the repository wear I1–I7 throughout, every
claim stays true, and nothing that works today stops working.

**How it is run.** Two parts, each its own `/next` with a review after it.

### Part 1 — the dashboard

**Carried from Phase 39 — C1, the N+1 route's page. First, as its own commit
after the review's, pushed at once so that CI measures it while the dashboard
work goes on.**

- **Why.** The N+1's cost is the runner's round trip. At a page of 200 its
  sample 45 has ranged 22.6 to 62.9 ms across CI's runners, so the 20 ms
  budget Q40 set is 2.6 ms under the fault on the fastest runner seen. A
  faster runner would read a pass where an N+1 is planted.
- **Measured in the architecture session's workspace** (Python 3.12,
  PostgreSQL 16 with the million-row seed, 50 requests 50 ms apart, three runs
  at each page; the page constant changed there, not in the repository):

  | Page | The join: slowest | The N+1: sample 45 | Body |
  |---|---|---|---|
  | 200 | 5.9–7.3 ms | 35.8–53.3 ms | 20 KB |
  | 400 | 8.7–9.0 ms | 71.5–81.8 ms | 41 KB |
  | 600 | 6.9–8.7 ms | 93.9–128.7 ms | 61 KB |

  The join's cost hardly moves with the page; the N+1's grows with it.

- **Decided:** `DETAILS_PAGE` is 500 (the default page and the `?limit=` cap),
  `response_items_max` 500 at `/products`, and `latency_p95_ms` 25, the
  products list's own budget. Projected from the fastest runner seen: the
  fault's sample 45 about 50 ms and the fix's slowest about 14 ms at worst,
  which is amended decision 4's margins (at least 37.5, at most 16.7) with
  room.
- **Checked in CI, from the LATENCY lines:** in every reading of at least two
  runs, the fault's sample 45 is at least 37.5 ms and the fix's slowest at
  most 16.7 ms. If either fails, report it as Q41 with the table. The
  dashboard work goes on, but the pull request is not marked ready until Q41
  is ruled.
- **Then:** the budgets' `why`s and LIMITS say page 500 and the measured
  range; `test_manifest_budgets.py`'s pins follow; the README's N+1 case is
  retaken from a green run's log, never written by hand. No harness check is
  added back (Q40). Every existing case keeps its root and verdict.

**Work order.**
0. **The assessment, written first in the report.**
   - Each route and its job.
   - The most important information on each screen.
   - The inconsistencies found today.
   - Which screens are data-heavy (the investigation view, the lists,
     settings), and so stay dense, solid and quiet.
   - Which are expressive (login, empty states, not-found), and so carry
     the graticule and the glow.
1. **Tokens.** `index.css` takes I2's values, keeping token names where the
   role is the same.
   - The highlight becomes `--culprit`.
   - Verdicts and severities are re-derived.
   - A type scale and radius, spacing and shadow steps are added.
   - `test_design_tokens.py` is updated, and gains the hue-separation test.
2. **Restraint, enforced (I7).** `check-frontend-tokens` restricts
   `--culprit` and the glass tokens to the components declared for them.
   Each restriction gets a mutation shown red.
3. **Components** (`components/ui`):
   - buttons: violet primary, with quiet secondary and ghost styles;
   - inputs and selects;
   - badges and verdict chips, with words;
   - cards;
   - dialog, popover, tooltip and command, in glass;
   - skeletons, and empty, error and success states;
   - violet focus rings at 2 px, offset.
4. **Screens.**
   - **The investigation view first.** The root statement is the
     editorial heading, with the lime marker. The fault tree's root node
     gets the lime outline. Evidence and readings are solid.
   - **Then:** the list, login, settings, not-found, and incidents and
     postmortems (consistency only).
5. **Motion (I6),** under the reduced-motion rule.
6. **The mark.** `Brand.tsx`'s dot becomes lime. `favicon.svg` becomes the
   mark, replacing Vite's default, with `docs/brand/mark.svg` and
   `wordmark.svg` beside it.
7. **e2e retakes the screenshots;** none is edited by hand.
8. **PRODUCTISATION.md** gains a status line: §2's palette is superseded by
   this plan's I1–I7 (owner, 2026-11-18). Its text is otherwise kept as it
   is.

**Acceptance criteria.**
- Every colour comes from a token. `check-frontend-tokens` and
  `test_design_tokens.py` pass, including the new restrictions and
  hue-separation test, and each mutation is red.
- Contrast: every text token is at least 4.5:1 on every surface it is used
  on, and every boundary and focus ring is at least 3:1.
- Lime appears only where the answer is marked. Glass appears only on
  layered components.
- With `reducedMotion: 'reduce'`, no transition runs (an e2e test).
- **Nothing is lost.** Every e2e assertion that held before still holds,
  at all four widths; every route is reachable; keyboard-only use still
  works. Only the screenshots change.
- The report shows every screen at 1280 px and one at 375 px, for the owner
  to judge the look.

**Do NOT:**
- remove functionality for appearance;
- add a dependency (the fontsource 700 weight is part of the installed
  package);
- add a light theme to the dashboard;
- animate data;
- commit the reference image.

### Part 2 — the repository

**Work.**
1. The hero and social preview (S2).
2. The re-themed captures (S1).
3. The diagrams.
4. The new README (S3), `docs/GUIDE.md`, and `scripts/check_readme.py`
   (S4).

**Acceptance criteria.**
- The README is under 300 lines, in S3's order, and every number in it is
  read from its source on the merge result.
- `check_readme.py` passes, and its mutations are red.
- The hero's figure equals the accuracy block's.
- Every capture is regenerated; none is edited by hand.
- The owner has looked at the rendered README on github.com in the light
  and dark themes.

**Human steps, after merge:** upload `social-preview.png`, and set the
repository's description and topics. The review gives the text.

### Review of part 1, 2026-11-18 — merged as `624c6e3` (PR #49)

**Part 1 is signed off.**

**CI.** Read by id from GitHub's API:
- 44333504867 on `61a0546` (C1): success on every job.
- 44336394900 on `8cba501` and 44338092108 on `ded4f19`: `e2e (none)` and `e2e
  (stub)` red on one tour test, because the diagnosis heading was a second
  `<header>` and `locator('header')` found two. Fixed in `1f3080a`. Every
  other job was green, both fault-library shards included.
- 44340916627 on `1f3080a`: success on every job.
- 44346373804 on `b234e12`, the report: success on every job. The pull request
  was merged after it finished. `main` had not moved from `33df658`, so the
  tree merged is `b234e12`'s.
- `main`'s push run 44375710199 on `624c6e3` was running at sign-off, with no
  job red; part 2's step 0 confirms it.

**C1 is met.** The fault's sample 45 and the fix's slowest answer, from the
LATENCY lines of two runs:
- 44333504867: the fault 144.3 and 142.6 ms; the fix at most 12.3 ms.
- 44336394900: the fault 102.1 and 98.5 ms; the fix at most 6.2 ms.

The bars were 37.5 and 16.7 ms. Those runners were slower than the projection
from the fastest one seen (about 50 ms), so the fault's margin is wide; the
fix stayed at the join's few milliseconds. On disk: `DETAILS_PAGE` 500,
`response_items_max` 500 and `latency_p95_ms` 25, the test pins, the library's
expected text ("ran 500 times for the 500 items"), and `results.json`
unchanged.

**Verified on disk,** on `624c6e3`, in the architecture session's workspace:
- `test_design_tokens.py` and `test_check_frontend_tokens.py`: 187 passed.
  `check_frontend_tokens.py`: 74 files, tokens only.
- **Three mutations of its own, each shown red and then restored:**
  - `text-culprit` in `Evidence.tsx`: the check exits 1, "culprit token
    outside the answer";
  - `--pass` moved to a lime-like `#b8e05a`: the hue test fails on pass
    against the culprit;
  - `--ring` darkened to `#6a39dd`: four ring pairs and the anchors test fail.
- No dependency changed: `frontend/package.json` and its lock file are
  untouched. The reference image is not committed. The e2e diff removes one
  comment and adds the motion test.
- The screenshots were looked at, at 1280 and 375 px. The investigation's
  answer is the page's heading, with the lime marker and rule; the fault
  tree's root carries the lime outline; a list row's root is lime and a
  stopped walk is sky blue; sign-in carries the graticule and the glow, on a
  solid card. The look is the owner's call: he approves it by starting part 2.

**The run's five decisions:**
1. The answer's heading is the root subject, in mono at display size, with the
   statement beneath as the diagnosis line: statements run past 300
   characters. Accepted.
2. Lime marks four places: the investigation's root and diagnosis line, the
   tree's root node, a list row's root, and the mark. A row's root is that
   row's answer. Accepted.
3. The ring is `#7540F5` itself, so controls must sit only on the well, the
   page, a panel or glass, where it measures 3.0 to 3.4:1; LIMITS says so.
   **Amended by C2:** nothing holds that placement, so a control put in a
   tinted box tomorrow would show a ring under 3:1 and no gate would notice.
   The ring becomes a lighter violet that clears 3:1 everywhere.
4. The graticule is an SVG of two paths, since a pattern fill would need a
   colour property the token gate refuses. Accepted.
5. A complete diagnosis with no remediation says "The walk suggests no fix for
   this root." It is true, and shown only in that case. Accepted.

**Accepted as left:** the phase auditor was not re-run after `ded4f19`; this
review's checks cover the change. **Noted, for C2:**
`check_frontend_tokens.py` ends a restriction failure with its summary line
about values that "bypass the design tokens", which is the wrong sentence for
it.

### Part 2 — brief (2026-11-18)

**Carried from part 1 — C2, the focus ring. First, as its own commit after the
review's.**
- `--ring` becomes `#8F63FF`, the violet at a higher lightness. Measured here,
  it clears 3.25:1 on all fifteen surfaces and tints (the lowest is
  `culprit-tint`), where `#7540F5` falls to 2.29:1. `#7540F5` stays the fill.
  I2 is amended: violet's fill is the anchor, and the ring is its lighter
  step.
- The ring test is built from the token names, as the text pairs are: the ring
  against every surface, every tint and glass. `RING_SURFACES` goes; the
  anchors test pins the fill, not the ring. The LIMITS entry "The focus ring
  is 3:1 only where controls sit" is removed.
- Mutations shown red: the ring back to `#7540F5`, and a new tint too light
  for it.
- The check's summary line counts restriction failures in a sentence of their
  own.
- The screenshots change only where a ring shows; e2e retakes them.

**Decided now for part 2:**
1. **The review copies go.** `docs/screenshots/phase-40-review/` is removed in
   C2's commit. Starting this part is the owner's approval of the look.
2. **One function gives the figure.** `scripts/accuracy_readme.py`, which
   already renders the README's accuracy block from `results.json`, also gives
   the hero its figure. The hero's renderer records the figure it drew in
   `docs/brand/hero.json`. `scripts/tests/test_accuracy_readme.py`, which
   already fails when the README's block is not what `results.json` renders,
   also fails when that file's figure is not: a stale hero is red. Its
   mutation is shown red.
3. **The hero is rendered** by the Playwright that `frontend/` already
   installs, from `docs/brand/hero.html`, with the installed fontsource fonts,
   through one recipe, `just readme-hero`. It writes `hero-dark.png` and
   `hero-light.png` (3200×800) and `social-preview.png` (1280×640) under
   `docs/brand/`. The README shows the pair through `<picture>` with
   `prefers-color-scheme`. No new dependency.
4. **Where each truth check runs.** `scripts/check_readme.py`, standard
   library only, joins `lint` for what a checkout holds: every relative link
   and image in `README.md` and `docs/*.md` resolves, and every probe count
   the README states equals the catalogue's. The self-check's figures are
   checked where they are produced: the self-check job hands its output to
   `check_readme.py`, which fails if a figure the README or `docs/GUIDE.md`
   quotes differs. Each check's mutation is shown red.
5. **The walk's diagram** is Mermaid, which GitHub renders, themed by an
   `init` block from I2's anchors; the root is lime with plum text, by a
   `classDef`. It shows the order the walk asks: errors, latency, N+1 where
   isolated, then the database pass.
6. **The README** follows S3's order and stays under 300 lines. The tutorial
   moves verbatim to `docs/GUIDE.md`, and every link into it is updated.
   "Future work" becomes S3's status section, read from the plans. The probe
   count says what the catalogue holds.
7. **The captures** take I2's colours in `render_captures.py`'s one constant
   block and are regenerated by `just readme-captures`. The dashboard's
   screenshots stay e2e's.
8. **The report** links the README as GitHub renders it on the branch, so that
   the owner can look at it in GitHub's light and dark themes before merging,
   as part 2's criteria ask.

**Do NOT:**
- add a shields.io badge, an emoji, or a dependency;
- draw any picture or type any figure by hand;
- delete any tutorial text without its home in `docs/GUIDE.md`;
- commit the owner's reference image.

---

## Phase 41 — The gate

**Goal.** D1–D6: `gate` required, strict, no bypass; the critical path at
12 minutes or less, measured.

**Work.**
- `gate`, with a mutation shown red.
- The fault library after `lint`.
- Four shards.
- `concurrency:` on pull requests.
- `timeout-minutes` on every job, at twice its slowest measured run.
- Docker layer caching, if it measures as a gain.
- The table of runs before and after.

**After merge (owner):** require `gate` in the ruleset, strict, with no
bypass actors. Check that a red throwaway pull request cannot merge, then
close it.

---

## Phase 42 — Ownership on the record

**Before it starts:** the owner confirms the name of record (Joshua Heath,
as `LICENSING.md` says). Any other owner needs a written assignment, not
just a different name in a file.

**Work:** D8. **Criteria:**
- `reuse lint` is clean, and red on a mutation;
- the SPDX map equals `LICENSING.md`'s;
- `CITATION.cff` validates;
- the CLA names its template;
- `AUTHORSHIP.md` states facts with pointers.

**After merge (owner):** the Software Heritage archive; private
vulnerability reporting; secret scanning with push protection.

---

## Phase 43 — Authenticated

**Before it starts (owner):** an SSH signing key on the machine Claude Code
runs on, added to the account as a signing key.

**Work:** D7. **Criteria:**
- no unpinned third-party action;
- an attestation verifies on `main`'s push run;
- every commit on the branch is Verified;
- no job gains a permission beyond the two attestation permissions.

---

## §4. Out of scope

- A merge queue.
- Required reviews from another person.
- Deploying.
- Registering the mark or the copyright.
- A light theme for the dashboard.
- Committing third-party reference images.
