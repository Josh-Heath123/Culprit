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

### Review of part 2, 2026-11-19 — merged as `cdc5032` (PR #50)

**Part 2 is signed off. Phase 40 is complete.**

**CI.** Read by id from GitHub's API:
- 44380261151 on `9a25806` (C2): `lint` red on one line over 100 characters,
  pushed before `just lint` ran; fixed in `b6d0328`. Every other job green.
- 44383181239 on `b6d0328` and 44386033657 on `18bf5a2`: success on every job,
  both fault-library shards included.
- 44390448565 on `721edfe`, the report: success on every job. The pull request
  was merged after it. `main` had not moved from `624c6e3`, so the tree merged
  is `721edfe`'s.
- `main`'s push run 44498857049 on `cdc5032`: running at sign-off, with no job
  red; Phase 41's step 0 confirms it.

**Verified on disk,** on `cdc5032`, in the architecture session's workspace:
- The token, restriction, README and capture tests: 229 passed;
  `test_accuracy_readme.py`: 8 passed. `check_readme.py`: 22 documents, true.
  `check_frontend_tokens.py`: 74 files, tokens only.
- **Four mutations of its own, each shown red and then restored:**
  - `hero.json`'s verified count set to 8: the hero test fails;
  - "19 read-only probes" in the README: "says 19 probes; the catalogue holds
    18";
  - a link to a file that does not exist, in `docs/GUIDE.md`: "does not
    resolve";
  - self-check output with 10 gaps: both quotes of "9 gaps" fail, in the
    README and the guide. Output holding no figure at all exits 2, cannot run,
    rather than passing.
- **Nothing was lost in the move.** Of the old README's 855 non-empty lines,
  all but 15 appear in the new README or `docs/GUIDE.md` with only their links
  rebased. The 15 are the three corrected statements, three cross-references,
  two headings and the "Future work" section, which became "Status" and still
  names the demonstration video.
- The hero, light and dark, and the social preview were looked at: the plum
  field, the graticule and the violet glow; the mark and the wordmark; the
  promise in mono capitals; and the one lime figure, "9 of 9", beside "100% of
  those decided · 11 planted in demo services". In the light variant, lime is
  a filled block with plum text.
- No dependency changed. The reference image is not committed.

**The run's notes:**
- **The optional `culprit diagnose` capture was not added,** as S1's own
  condition says: no command renders a recorded walk as text. Accepted.
- **The diagrams stay plum in GitHub's light theme,** since Mermaid takes one
  theme per diagram; LIMITS says so. Accepted.
- **The phase auditor was not re-run after `eb8f53a`;** this review's checks
  cover the fixes.
- **C2 was pushed before `just lint`.** The run said so plainly; Phase 41's
  gate makes a red `lint` unmergeable: the protection is the gate, not
  discipline.

**The criterion "every number in it is read from its source" is amended,** as
the phase auditor proposed: every number the README states is held by a named
check whose mutation is red, or listed in the run's report as audited by hand,
with its source. Prose numbers cannot all be checked; the report lists which
are held and which were audited.

**Fixed in this review:** LIMITS's "The README's number is five planted
faults" was out of date. It is rewritten to say what holds now, with no count
in it to go stale.

**The owner merged on 2026-11-19,** after the report asked him to look at the
README in both themes. His remaining steps are GitHub settings: the social
preview, and the description and topics, whose text the architecture session
gave him in chat.

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

### Brief (2026-11-19)

**What the workflow holds today** (`ci-cd.yml` on `cdc5032`, and three green
runs):
- The graph: `lint` → `typecheck` → `test` and `migration-round-trip`; `lint`
  → `cli` → `self-check`, `kind-capture`, `fault-library` (two shards) and,
  with `test`, `build`; `lint` → `e2e` (two narrations) → `narration-parity`;
  `deploy` only on a manual dispatch.
- **The critical path is `lint` → `cli` → `fault-library (2)`:** 22.0, 23.4
  and 24.2 minutes in runs 44383181239, 44386033657 and 44390448565. `cli`
  takes 6.1–8.2 minutes, shard 1 11.8–12.2, shard 2 15.5–16.4, and `e2e`
  9.0–11.1.
- **The fault library uses nothing `cli` produces:** its job checks out, sets
  up Go, and runs the library, which builds the binary itself.
- **No job has `timeout-minutes`** except `e2e` (75) and `narration-parity`
  (5). There is no `concurrency:` block.
- **Shards are assigned by a rule over the library** (`shardOf`: the inventory
  environments' cases in shard 2), held by
  `TestTheFaultLibraryShardsCoverEveryCaseOnce`; `faultLibraryShards` is a
  constant beside the workflow's matrix.

**Decided now:**
1. **The gate's decision is code.** `scripts/ci_gate.py`, standard library
   only, reads `toJSON(needs)` and fails unless every needed job's result is
   `success`, printing each job and its result.
   `scripts/tests/test_ci_gate.py` holds it on success, failure, skipped and
   cancelled, each a mutation shown red.
2. **The `gate` job runs `if: always()`.** On GitHub a skipped required check
   counts as passed, so a gate skipped because `lint` failed would let the
   pull request merge. Run always, it fails on the skips instead.
3. **What the gate needs is held structurally.** A test parses `ci-cd.yml` and
   requires `gate`'s `needs` to be every job but `gate` and `deploy`. `deploy`
   is named, with its reason: it runs only on a manual dispatch, after `build`
   and `e2e`. A job added later and left out of the gate fails that test. The
   same test requires `timeout-minutes` on every job, and that `concurrency:`
   cancels superseded runs on pull requests only, never a push to `main`.
4. **The fault library needs `lint` only.** The shards start when `cli` does.
5. **Shards: as many as the target needs, four to start.** They are balanced
   from per-case times read from CI's logs (`--- PASS` lines), by a rule over
   the library or a field declared in `expected.json`, never a list of names.
   The shard test also requires the workflow's matrix to be exactly 1 to
   `faultLibraryShards`. Each shard keeps the results check.
6. **Timeouts:** each job's is twice its slowest run in the last ten green
   runs, rounded up to 5 minutes, and at least 10. The library's own `go test
   -timeout` stays.
7. **Docker layer caching only if two runs show the gain.** Any action it adds
   is pinned to a commit SHA, ahead of D7.
8. **D4's "the database boundary as its own job" is dropped:** `test` takes
   about 3 minutes and is not on the critical path.
9. **Measured.** The report gives the table before (the three runs above) and
   after (at least two runs): the wall time, the critical path and each job's
   time. If `e2e` (9–11 minutes) becomes the critical path and the 12-minute
   target is missed, report what bounds it; nothing in `e2e` is removed for
   time.
10. **Every red job in the run's CI is attributed** in the report (D6),
    including any won on a rerun.

**Do NOT:**
- add a path filter, a retry, `continue-on-error` or a merge queue;
- remove, skip or loosen any test, check or precondition for speed (D5);
- change what any job checks; only where and when it runs;
- touch the ruleset: that is the owner's step after merge.

**After merge (owner), with the steps given at the review:** require `gate` in
the ruleset, with branches up to date and no bypass actors; then open a
throwaway pull request with a deliberately failing test, see that it cannot
merge, and close it.

### Review, 2026-11-19 — merged as `3928f0a` (PR #51)

**Phase 41 is signed off.**

**CI.** Read by id from GitHub's API:
- 44503311197 on `143839f`, 44516832208 on `b785cab` and 44519127072 on the
  report, `2cffe14`: success on every job on the first attempt, with `gate`
  among them; only `build / publish` and `deploy` skipped, as on every pull
  request. Nothing red to attribute.
- The wall times were 12.4, 13.2 and 12.8 minutes, against 22.0 to 24.2
  before. Each of the four shards took 7.1 to 8.3 minutes; `e2e (stub)`, at
  11.9 to 12.7, now sets the time.
- The pull request was merged after the report's run finished. `main` had not
  moved from `cdc5032`, so the tree merged is `2cffe14`'s.
- `main`'s push run 44522173729 on `3928f0a`: red on one job and the gate.
  `e2e (stub)` failed in "Install Chromium for Playwright", before any test
  ran, after the step before it spent two and a half minutes in `apt-get`;
  `e2e (none)` passed the same step on the same commit, and every other job
  was green. `gate` failed on it, as it should. Phase 42's step 0 reads that
  job's log (job 135553437405), records the cause, and reruns the failed jobs
  (D6).
- The check GitHub reports is named `gate`, from the GitHub Actions app: the
  name the ruleset is to require.

**Verified on disk,** on `3928f0a`, in the architecture session's workspace:
- `test_ci_gate.py` and `test_ci_workflow.py`: 31 passed.
- **Three mutations of its own, each shown red and then restored:**
  - `kind-capture` taken out of the gate's `needs`: "the gate needs every job
    but deploy" fails;
  - a new job with no timeout and no place in the gate: the needs test and the
    timeout test both fail;
  - `ci_gate.py` made to accept `skipped`: the tests on a skipped shard and on
    a gate after a failed `lint` fail.
- The shards come from declared seconds in `expected.json`, assigned longest
  first to the lightest shard, and the Go shard test holds the workflow's
  matrix to 1 to `faultLibraryShards`.

**Rulings on what the run left open:**
1. **The 12-minute target: missed by 0.4 to 1.2 minutes, and accepted.** What
   bounds it is `e2e (stub)` building every image for the quickstart, about 4
   minutes, as a user's quickstart does. The cut from 23 minutes to 13 came
   from moving work, not from removing any of it. D4's target is amended to
   the measured 12.4 to 13.3 minutes.
2. **Docker layer caching: not now.** The images on the critical path are
   built inside `just quickstart`, and e2e exists to run the quickstart as a
   user does. Caching them means a build path that only CI takes, and a new
   action, for at most part of 4 minutes. It stays a named option, to take up
   if the critical path grows.
3. **Test timeouts inside job timeouts: carried into Phase 42 as C3.** A job
   timeout equal to its test's `go test -timeout` (`cli`'s database step, and
   the agent test in `e2e`) kills the job before Go can print the stack that
   names the hung test. The gate still fails, so nothing merges; but the hang
   goes unattributed, against D6.

**Decision 6 as built:** the timeouts are twice each job's slowest of the last
ten green runs, rounded up to 5 minutes, and at least 10; `build`'s 15 comes
from run 44321940704's 5.3 minutes, which the comment names. Accepted.

**The owner decided on 2026-11-19** that the name of record is Joshua Heath,
and that Culprit's documents call the owner Joshua throughout. This review
makes the change in every tracked file (47 mentions of another first name, in
five files); git history is not rewritten.

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

### Brief (2026-11-19)

**The name of record is Joshua Heath,** confirmed by the owner on 2026-11-19,
as `LICENSING.md` and the README already say. The work began on 2026-08-02
(the first commit), so every copyright line reads 2026.

**Carried from Phase 41 — C3, test timeouts inside job timeouts. First, as its
own commit after the review's.**
- Every `go test -timeout` a job runs, in the workflow or in a `just` recipe
  it calls, is at most half that job's `timeout-minutes`, so Go's own timeout
  fires first and prints the stack.
- **Concretely:** `cli`'s database step 10 minutes (job 20), the agent end to
  end 15 (`e2e`, job 30; it takes about 2.5), and the fault library 17 (job
  35; a shard takes 7 to 8). The local `just fault-library` keeps 30, since it
  runs every case in one go.
- `test_ci_workflow.py` holds the rule over the workflow and the recipes it
  calls, with a mutation shown red. The LIMITS entry about the two timeouts
  that could not fire goes.

**What the repository holds today** (`git ls-files` on `3928f0a`):
- 941 tracked files: 352 Python, 185 Go, 100 JSON, 52 Markdown, 86 TypeScript
  and TSX, 47 YAML, and the rest shell, TOML, SQL, CSS, HTML, SVG, PNG and
  lock files.
- `LICENSING.md` maps the licences: `AGPL-3.0-only` by default; `Apache-2.0`
  for `extractors/python/`, `extractors/node/` and `shared/`, each with its
  own `LICENSE`; and the two third-party fixtures under
  `cli/testdata/fixtures/third-party/`, which keep their own (BSD-3-Clause and
  MIT).
- Many JSON files, goldens and recorded outputs are compared byte for byte by
  tests, and some files are generated (the catalogue, `results.json`,
  `hero.json`, the captures, lock files).

**Decided now:**
1. **REUSE, with headers where a file can hold a comment and `REUSE.toml`
   everywhere else.** Source files (Go, Python, TypeScript, CSS, shell, SQL,
   YAML, TOML, HTML, Dockerfiles) carry `SPDX-FileCopyrightText: 2026 Joshua
   Heath` and their `SPDX-License-Identifier`. JSON, goldens, recorded
   outputs, generated files, images and lock files are annotated in
   `REUSE.toml`, so no byte a test compares changes. `LICENSES/` holds each
   licence's text; every existing `LICENSE` file stays, since GitHub detects
   the licence from them.
2. **The third-party fixtures keep their own licences and holders,** annotated
   in `REUSE.toml` from their own `LICENSE` files. Nothing of Culprit's is
   claimed over them.
3. **One map, read twice, agreeing.** A test holds `LICENSING.md`'s table to
   what REUSE reports for files under each path: every path in the table
   resolves to its SPDX identifier.
4. **`reuse lint` runs in `lint`,** the tool pinned to one version and run
   with `uvx`, not added to any project's dependencies. A new file without a
   header or an annotation turns it red: the mutation. `CLAUDE.md` gains one
   line saying so.
5. **NOTICE:** the copyright holder, the licence split (pointing at
   `LICENSING.md`), and the third-party material the repository holds or its
   builds ship: the two fixtures, and the Inter and JetBrains Mono fonts (SIL
   Open Font License 1.1) that the dashboard bundles and the hero renders. The
   container images' bundled dependencies are not listed; LIMITS says so, and
   Phase 43's attestations are where a software bill of materials belongs.
6. **`AUTHORSHIP.md` states facts, each with a pointer to its evidence, and no
   legal conclusion.** It says:
    - who directs the work, decides it, reviews it and merges it: Joshua
      Heath;
    - how it is made: much of the code and many of the documents were written
      by Claude (Anthropic's model), in Claude Code and an architecture
      session, under his direction. The pointers are the commits'
      `Co-Authored-By` trailers, the plans' recorded decisions and rulings,
      and the pull requests he merged;
    - that Anthropic's consumer terms assign to the user whatever rights
      Anthropic has in outputs, with a link to the terms, paraphrased and
      dated;
    - that copyright in AI-assisted work depends on the law where it is
      claimed, with links to the US Copyright Office's January 2025 report on
      copyrightability and South Africa's Copyright Act (which names as author
      of a computer program the person who controlled its making). It says
      plainly that the file is not legal advice.
7. **`CONTRIBUTING.md` and the CLA.** The CLA is the Project Harmony
   individual contributor agreement, the licence form (not an assignment),
   named with its version, with Joshua Heath as recipient. The report records
   the outbound option chosen and why: the default is the one that lets the
   owner offer Culprit under other licences, so a hosted service stays
   possible. Until a lawyer has read it, CONTRIBUTING says outside code
   contributions are not yet accepted; issues and reports are welcome.
8. **`TRADEMARKS.md`:** "Culprit" and the mark (`docs/brand/mark.svg`) are
   unregistered marks of Joshua Heath; describing or linking to the project is
   fine; a fork or a hosted service of a modified version uses another name
   and mark. No claim of registration.
9. **`CITATION.cff`,** validated in `lint` by a pinned `cffconvert --validate`
   run with `uvx`, red on a mutation (a missing required field).
10. **`SECURITY.md`:** report privately through GitHub's private vulnerability
    reporting, which the owner turns on after merge; what is in scope (the
    CLI's read-only guarantees, the control plane, the MCP server, the
    extractors); only `main` and the latest release supported; an honest
    response time for a project with one maintainer, and no bounty.
11. **The README's author line** points at `AUTHORSHIP.md` and `NOTICE`,
    inside the 300-line limit; `check_readme.py` still passes.

**Do NOT:**
- rewrite history, or change any licence;
- put a header on any file a test compares byte for byte, or on a generated
  file;
- claim a registered mark, or give legal advice;
- put any email address, student number or local path in any of these files;
- accept, or invite, an outside code contribution before the CLA is reviewed.

**After merge (owner), with the steps given at the review:** save the
repository to Software Heritage; turn on private vulnerability reporting; turn
on secret scanning with push protection.

### Review, 2026-11-19 — merged as `bb92e48` (PR #53)

**Phase 42 is signed off.**

**CI.** Read by id from GitHub's API:
- 44534379764 on `dc6e835`, 44543993249 on `3aeeaf4` and 44546655296 on the
  report, `06af385`: success on every job, `gate` included. The pull request's
  CodeQL check failed on `dc6e835` (Q41, below) and passed on `3aeeaf4` and
  `06af385`: no new alert in the code it changed.
- The pull request was merged after the report's run, with `gate` required:
  the ruleset now lists `gate`, strict, with no bypass, and a throwaway pull
  request with a failing test (#54) read BLOCKED.
- `main`'s push run 44563572561 on `bb92e48`: success on every job, `gate` and
  `build / publish` included (`deploy` skipped: deploy is paused).
- Step 0 attributed the red `e2e (stub)` of push run 44522173729: `apt-get`,
  inside `playwright install --with-deps`, could not reach Ubuntu's archive
  (connection timeouts to two mirrors); no test ran. Rerun green. Ambient, not
  the code (D6).

**Verified on disk,** on `bb92e48`, in the architecture session's workspace:
- `49fa66c`, the headers: 668 files, 1,982 insertions and no deletion; every
  inserted line is an SPDX tag or the blank after it; no JSON file and nothing
  under any `testdata/` touched.
- `reuse lint` (6.3.0, as pinned) compliant, and `check_licensing_map.py`: 942
  files, seven rows of `LICENSING.md`, agree. `cffconvert` 2.0.0: valid. The
  workflow, gate, map and README tests: 81 passed.
- **Two mutations of its own, each shown red and then restored:** an unheaded
  new file under `worker/` ("REUSE says nothing, LICENSING.md says
  AGPL-3.0-only"); a file under `extractors/python/` headed AGPL ("REUSE says
  AGPL-3.0-only, LICENSING.md says Apache-2.0").
- C3: every `go test -timeout` in the workflow is at most half its job's (10,
  5 and 17 minutes; the agent's 15 in its recipe).
- The CLA's Option Five is the Harmony template's own: the contribution may be
  licensed under any licence, including commercial or proprietary ones
  (harmonyagreements.org, the combined template, section 2.3).

**Q41, ruled during the run** (three code-scanning alerts, open on `main`
since 2026-11-04, surfaced when the headers put a line into every file):
- **#3** (`scripts/bootstrap_env.py`, the quickstart's admin password printed)
  was fixed, not dismissed: the password was already in `infra/.env.prod`
  (mode 0600), the quickstart already shows it at the end locally, and the
  printed line was filtered out under CI. The script now says where it is; the
  filter is gone; a test fails if anything generated is printed.
- **#2** (`api/scripts/apply_model.py`, a new component's API key printed
  once) is the owner's to dismiss as "won't fix": the key exists only as a
  hash, and this is the one way to hand it over, as the HTTP API does.
- **#4** (`api/app/ingest_gateway/auth.py`, SHA-256 of API keys) is the
  owner's to dismiss as a false positive: the keys are 256 random bits
  (`secrets.token_urlsafe(32)`), not passwords; operator passwords use argon2.
- **The dismissals in GitHub went to #3 and #4,** not #2 and #4. #3 is fixed
  in the code, so the owner reopens it and the next analysis on `main` closes
  it as fixed; #2 is dismissed as "won't fix" if it is not already. Phase 43's
  step 0 reads the alerts and reports their states.

**The run's decisions: accepted.**
- Headers on every file that holds a comment, including the justfile, ignore
  files and the systemd unit; `REUSE.toml` by file type outside the test data
  and by directory inside it; shebangs and doctypes kept first.
- `check_licensing_map.py` reading `reuse lint --json` from a pipe without
  `pipefail`: safe, since the script fails on a non-compliant report and on
  empty or broken input.
- LICENSING.md's table now names an identifier in every row, with `deploy/`
  and the fixtures' manifests; no licence changed.
- The CLA linked, not copied, with its media licences, governing law and
  signing left open for the lawyer; outside code closed until then.
- C3 extended to `kind-capture` (5 minutes, within its job's 10), by the same
  rule.

**Corrected in this review:** `AUTHORSHIP.md` said every change reaches `main`
through a pull request. 26 commits were pushed to `main` directly, the last on
2026-11-05; every change since has come through a pull request, and since
2026-11-19 the ruleset requires it. The file now says so, with the command
that counts them.

**Not re-run:** the phase auditor after `0716dee`, and both auditors after
Q41's fix; this review's checks cover them.

---

## Phase 43 — Authenticated

**Before it starts (owner):** an SSH signing key on the machine Claude Code
runs on, added to the account as a signing key.

**Work:** D7. **Criteria:**
- no unpinned third-party action;
- an attestation verifies on `main`'s push run;
- every commit on the branch is Verified;
- no job gains a permission beyond the two attestation permissions.

### Brief (2026-11-19)

**What the workflows hold today** (`.github/workflows/` on `bb92e48`):
- Three workflows: `ci-cd.yml`, `images.yml` (called by it) and
  `cli-release.yml` (on a `v*` tag, or by hand).
- **No `uses:` is pinned to a commit.** Sixteen actions by tag or branch:
  `actions/checkout`, `setup-go`, `setup-node`, `upload-artifact`,
  `download-artifact`, `astral-sh/setup-uv`, `helm/kind-action`, the three
  `docker/*`, `aquasecurity/trivy-action`,
  `github/codeql-action/upload-sarif`, `softprops/action-gh-release`,
  `pypa/gh-action-pypi-publish@release/v1` (a branch) and the two `appleboy/*`
  that `deploy` uses.
- There is no `.github/dependabot.yml`.
- **What is published:** `images.yml`'s `publish` job, on a push to `main`,
  retags the five scanned images and pushes them to `ghcr.io` with `docker
  push`, holding `packages: write`. No release has been cut, so
  `cli-release.yml` has never published a binary.
- Commits are not signed.

**Decided now:**
1. **The signing key is made in step 0, on the owner's machine, by Claude
   Code.** An ed25519 key at `~/.ssh/culprit_signing`, refusing to overwrite
   one that exists, with no passphrase, so that commits can be signed
   unattended. It is for signing only, and is never added as an authentication
   key. Git is configured for this repository alone (`git config --local`):
   `gpg.format ssh`, `user.signingkey` the key, `commit.gpgsign` and
   `tag.gpgsign` on, and an allowed-signers file so that `git log
   --show-signature` verifies locally. Claude Code prints the public key and
   waits while the owner adds it on GitHub as a **signing** key. LIMITS says
   what a passphrase-less key on the laptop means.
2. **Every commit on the branch is Verified,** the review's commit included:
   GitHub's API (`commits/<sha>`, `verification.verified`) for each, in the
   report.
3. **Every external action is pinned to a full commit SHA,** with the version
   as a comment (`@<40 hex> # v4.2.2`), resolved from the tag the workflow
   uses today; no version changes in this phase. `pypa/gh-action-pypi-publish`
   is pinned to the commit its `release/v1` names. A local reusable workflow
   (`./`) is not an action. `test_ci_workflow.py` holds it over all three
   workflows: a tag or a branch in any `uses:` turns it red.
4. **Dependabot keeps the pins current:** `.github/dependabot.yml`, the
   `github-actions` ecosystem, weekly, every update grouped into one pull
   request, which must pass `gate` like any other. No other ecosystem's
   version updates in this phase.
5. **Attestations on what `main` publishes.** In `publish`, after each push,
   `actions/attest-build-provenance` (pinned) attests the image by its pushed
   digest, with `push-to-registry`, and `gh attestation verify` checks it in
   the same job; a failed verify fails the job. An SBOM of each image, written
   by the Trivy the job already has, is attested with `actions/attest-sbom`.
   `cli-release.yml` attests the binaries it builds, and verifies them; a run
   started by hand on the branch shows it works.
6. **Permissions:** only the jobs that attest gain `id-token: write` and
   `attestations: write`. `test_ci_workflow.py` holds every job's permissions
   to a declared table, so any other widening turns it red.
7. **LIMITS:** the attestations are in Sigstore's public log, since the
   repository is public, so the private images' names and digests are public
   there; a passphrase-less signing key; attestations exist only from this
   phase on.

**Do NOT:**
- add the key as an authentication key, or give it a passphrase the run would
  need typed;
- change any action's version while pinning it;
- publish, release or deploy anything: the attestation is proved on `main`'s
  push run after merge, and on the branch only through `cli-release.yml`
  started by hand;
- touch the ruleset.

**After merge (owner), with the steps given at the review:** require signed
commits in the ruleset, and allow only merge commits; turn on Dependabot
security updates. Then the delivery plan is complete.

### Review, 2026-11-19 — merged as `090cc4b` (PR #55)

**Phase 43 is signed off, and with it the delivery plan.**

**CI.** Read by id from GitHub's API:
- 44573995497 on `6d2bffc`, 44579250490 on `f56b4e4` and 44581822123 on the
  report, `072f075`: success on every job, `gate` included.
- `cli-release.yml` started by hand on the branch, 44574017581: the five
  binaries built, attested and verified; nothing published.
- `main`'s push run 44597852296 on `090cc4b`: `publish` attested and verified
  the provenance and the SBOM of all five images, as decided. But
  `narration-parity` failed in its one step, the comparison of the loop's
  records with narration on and off, so `gate` is red on `main`. The same tree
  passed it on the pull request (44581822123), and neither e2e job failed, so
  the merge did not change the code it compares. C4's step 0 reads that job's
  log (job 135829202240), attributes it, and reruns the whole run for fresh
  records; if the records differ for a reason in the code, it stops with Q42
  (D6).
- **Every commit is Verified** by GitHub's API: the five on the branch, signed
  with the repository's SSH signing key, and the merge commit, signed by
  GitHub.

**Verified on disk,** on `090cc4b`, in the architecture session's workspace:
- All 56 `uses:` lines across the three workflows that name an action are
  pinned to a full commit, with the version as a comment;
  `test_ci_workflow.py`: 60 passed.
- **Two mutations of its own, each shown red and then restored:** one
  `actions/checkout` pin put back to `@v4` ("every action is pinned to a
  commit" fails); `id-token: write` added to `images.yml`'s `build` ("every
  job holds its declared permissions" fails).
- `.github/dependabot.yml`: the `github-actions` ecosystem, weekly, one group.
  Its first update check ran within a minute of the merge.

**The run's notes:**
- **The verifies check only which repository signed,** so a build started by
  hand on a branch passes the same check. **Ruled: tighten it,** as C4
  (below).
- **The branch run's binary attestations are permanently in Sigstore's public
  log.** Accepted; LIMITS records it.
- **The auditors found four ways around the new checks** (a verify softened to
  always pass, a flow-style `uses:`, `.yaml` workflows, and a new workflow
  missing from the permissions table); all closed in `f56b4e4` and shown red.
- **The key's missing passphrase could not be confirmed** by a command, since
  the shell refused it; the key was made by the run without one, and LIMITS
  says what that means.

**The delivery plan is complete.** The dashboard and the repository wear the
new identity (Phase 40); every merge passes one required check, in about 13
minutes (41); every file states its licence and the project its ownership
(42); and every commit is signed, every action pinned, and what `main`
publishes attested (43). The owner's last steps are the ruleset's signed
commits, merge commits only, and Dependabot security updates.

### Close-out — C4, the signer workflow (brief, 2026-11-19)

**Decided:**
1. **Every `gh attestation verify` names the workflow that must have signed,**
   with `--signer-workflow`, and the ref, with `--source-ref`: `images.yml` on
   `refs/heads/main` in `publish`, and `cli-release.yml` on the tag being
   released (or the run's own ref when started by hand). A build from any
   other workflow or ref then fails it. Confirm on the run which workflow the
   certificate names when `images.yml` is called by `ci-cd.yml`, and use that.
2. **`test_ci_workflow.py` requires both flags on every verify** in every
   workflow; a verify without them turns it red: the mutation.
3. **Users get the command.** A short section, "Verifying what Culprit
   publishes", in `docs/GUIDE.md`, linked from `SECURITY.md`: the exact `gh
   attestation verify` for an image from `main` and for a released binary,
   each with both flags, and what a pass proves and does not.
4. **Proof:** the pull request's own run cannot publish, so the run starts
   `cli-release.yml` by hand on its branch and shows the tightened verify pass
   there; `publish`'s verify is confirmed on `main`'s push run after merge.

**Do NOT:**
- publish, release or deploy anything;
- change any action's version;
- touch the ruleset.

### Review of the close-out, part 1 — Q42 and Q43, merged as `527d965` (PR #64), 2026-11-20

**Q42 and Q43 are signed off. C4 was not started:** the run stopped at Q44, as
instructed. The owner merged the draft once Q42 and Q43 were green on the
merge result, so C4 runs on a new branch, briefed again below as amended by
Q44.

**CI.** Read by id from GitHub's API:
- 44748685372 on `cc21141` (the merge result with `03c309d`) and 44750683640
  on the report, `ed13ef2`: success on every job, `narration-parity` and
  `gate` included; `publish` and `deploy` skipped, as on every pull request.
- `main`'s push run 44755314601 on `527d965`: success on every job (25;
  `deploy` skipped), `narration-parity` and `gate` included; all five
  `publish` jobs attested and verified their images, with today's
  repository-only check, which C4 tightens.
- **Step 0.** 44707603837's red `build (mcp_server)` was its "Trivy scan" step
  (the jobs API; the advisory, in mcp 1.29.0, read from the log by Claude
  Code), fixed by #58's bump. Attributed, not a flake (D6).
- **Every commit is Verified** by GitHub's API: `e8442fe`, `aec7317`,
  `eda2da3`, `baea86d`, `cc21141` and `ed13ef2`, signed with the repository's
  SSH signing key, and the merge commit `527d965`, signed by GitHub.

**Verified on disk,** on `527d965`, in the architecture session's workspace
(Go 1.27.0):
- `go test ./internal/model/ ./internal/capture/ ./internal/verify/`: ok.
  `shared/tests/test_shape.py`: 80 passed.
  `api/tests/test_value_shape_vocabulary.py`: 4 passed, with no database.
- **Five mutations of its own, each restored afterwards:**
  - the IPv6 branch made to need one colon, in Go and in Python: the `formats`
    fixture red in both, on `ab:cd`;
  - a literal only in the migration's `_SCHEMES`: the vocabulary test red,
    naming it as only in the migration;
  - a throwaway head migration naming the *intent* constraint, with
    `_LENGTH_CLASSES` one short: the test followed the chain to it and went
    red;
  - the identity rule widened from equality to containment: the capture test
    red ("Identity = 3, want 2");
  - **one survived:** the empty-hostname guard removed (`own != ""`), every
    test still green. The "empty" subtest's environment holds no empty value,
    so it cannot tell. Carried as C5.

**The run's decisions:**
- **Q43's test is built as ruled,** and also refuses an orphan or a cycle on
  the chain. Accepted.
- **Part (b) needs no UPGRADING note.** Accepted: `Equivalent` compares on
  presence alone when either side is unknown, so an older binary's shaped
  value against a newer binary's unshaped one is no difference.
- **Q44 was raised correctly,** with the certificate read from a real run: the
  signer is the called workflow, `images.yml@refs/heads/main`. Ruled below.

**Rulings:**
- **Q42, the verification record not repeatable.** (a) IPv6 needs two colons,
  in Go and Python, with format classification in `shape_conformance.json`,
  read by both. (b) In the process adapter only, a variable whose value equals
  `os.Hostname()` is the runtime's identity: recorded present, its value
  unshaped, keyed on that OS fact and never on a name. (c) Rejected: `verify`
  keeps counting every unexplained difference. Also rejected: `HOSTNAME` by
  name, any list of names, loosening `narration-parity`, a retry. The full
  text is `q42-ruling.md` in the owner's outer folder.
- **Q43, the coupled-file pair.** The `shape.py` and `e4c1b7a9d2f0` pair is
  removed. The vocabulary's agreement is held by content: a database-free test
  finds the vocabulary's migration on the Alembic chain by AST and compares
  its four tuples with the four enums. The pair passed on any edit to the
  migration and never proved the vocabularies agree, and a check that can be
  passed only by gaming it is a defect. The applied migration was not touched.
  The full text is `q43-ruling.md`.
- **Q44, the ref `publish` verifies.** `publish` runs on `main` and on `v*`
  tags, so its verify names `--source-ref "$GITHUB_REF"`, not
  `refs/heads/main`, after a first step that refuses any ref `ci-cd.yml` does
  not push on. Decision 1 of C4, below.

**Carried:**
- **C5.** The identity rule's empty-hostname guard is held by no test that can
  fail. Give the capture test an empty-valued variable, assert it stays shaped
  when the hostname is empty, and show the guard's removal red.

### Close-out — C4, the signer workflow, as amended by Q44 (brief, 2026-11-20)

The 2026-11-19 brief stands, with decision 1 replaced, decision 2 sharpened,
and C5 first.

**Decided:**
1. **Every `gh attestation verify` names the workflow it runs in and the ref
   the run is on:** `--signer-workflow
   "$GITHUB_REPOSITORY/.github/workflows/<that file>"` and `--source-ref
   "$GITHUB_REF"`. The certificate names the called workflow (`images.yml`,
   confirmed on 44711807845), so in both workflows it is the file the verify
   sits in.
   - **In `publish`, a first step,** before logging in or pushing, fails
     unless `GITHUB_REF` is `refs/heads/main` or a `refs/tags/v*` tag, and
     names the ref it got. `--source-ref "$GITHUB_REF"` then means `main` or
     the tag being released, and nothing else.
   - **`cli-release.yml` is as decided:** its ref is the tag, or the run's own
     ref when started by hand.
2. **`test_ci_workflow.py` holds it, structurally:**
   - every verify in every workflow carries both flags, `--signer-workflow`
     naming the file the verify is in and `--source-ref` taking `$GITHUB_REF`;
   - `publish`'s guard comes before its first push, and the refs it accepts
     are read from `ci-cd.yml`'s `on.push` (branches and tags), so widening
     one without the other is red before merge;
   - mutations shown red: `--source-ref` dropped from one verify;
     `cli-release.yml`'s verify naming `images.yml`; a branch added to
     `ci-cd.yml`'s `on.push` with the guard unchanged.
3. **Users get the command,** as decided: for an image from `main`
   (`refs/heads/main`), for a release's image (`refs/tags/vX.Y.Z`) and for a
   released binary, each with both flags, the SBOM form included. Say what a
   pass proves (these bytes, built by that workflow in this repository from
   that ref) and what it does not (that the code is right, or that whoever
   pushed to `main` or cut the tag meant well). Say plainly that the packages
   are private and no release exists yet, so the commands become usable when
   the owner publishes.
4. **Proof,** as decided: a hand-started `cli-release.yml` run on the branch
   passes the tightened verify, and `publish`'s passes on `main`'s push run
   after merge. **The tag path cannot run until the owner cuts the first `v*`
   tag;** until then the workflow test holds it, and LIMITS says so.
5. **C5 first,** in its own commit.

**Do NOT:**
- publish, release or deploy anything, or cut a tag;
- change any action's version;
- touch the ruleset.

### Review of the close-out, part 2 — C4 and C5, merged as `91f62fb` (PR #65), 2026-11-20

**C4 and C5 are signed off, and with them Phase 43 and the delivery plan.**

**CI.** Read by id from GitHub's API:
- 44760584788 on `a1d5757`, 44766464671 on `0128be5` (the merge result) and
  44768657523 on the report, `3ee8b62`: success on every job; `publish` and
  `deploy` skipped, as on every pull request.
- `cli-release.yml` started by hand on the branch, 44758619408 on `a1d5757`
  and 44766453375 on `0128be5`: "Attest the binaries' build provenance" and
  "Verify every binary's attestation" success, the verify with both flags;
  Publish skipped; no tag cut.
- `main`'s push run 44798857512 on `91f62fb`: success on every job (25;
  `deploy` skipped), `narration-parity` and `gate` included. In all five
  `publish` jobs, "Refuse a ref ci-cd.yml does not push on" and the tightened
  "Verify both attestations" passed: decision 4's second half.
- **Every commit is Verified** by GitHub's API: `504bf4d`, `0095364`,
  `a1d5757`, `0128be5` and `3ee8b62`, and the merge commit `91f62fb`.
  `504bf4d`'s tree is exactly the review patch's.

**Verified on disk,** on `91f62fb`, in the architecture session's workspace:
- `scripts/tests/test_ci_workflow.py`: 68 passed. `go test ./internal/capture/
  ./internal/verify/ ./internal/model/` (Go 1.27.0): ok.
- **Six mutations of its own, each red and then restored:**
  - `publish`'s guard moved after the login: the guard test red;
  - `images.yml`'s provenance verify pinned to `refs/heads/main`: "every
    verify names its workflow and its ref" red;
  - the guard's fallback arm made to exit 0: the guard test red;
  - the guard widened to every tag (`refs/tags/*`): the guard test red;
  - the hostname's read error ignored: the capture test red;
  - the empty-hostname guard removed, which survived the last review: now red.
    C5 is closed.
- `docs/GUIDE.md`'s commands name the images and binaries as `images.yml` and
  `cli-release.yml` build them, and say plainly that none can be fetched yet.

**The run's decisions, accepted:**
- **The audits' three findings,** fixed in `0128be5` and each shown red first:
  the verifies' line continuations and the test's join, every arm of the guard
  read, and LIMITS' wording.
- **The shell's `v*` also matches a slash,** which the trigger's glob does
  not. It cannot be reached, since no trigger delivers such a ref to
  `publish`. Not changed.
- **The binaries' certificate could not be fetched by digest.** The verify
  step's success under `bash -e`, with a count of five, is the evidence.

**The delivery plan is complete.** Every attestation verify now names the
workflow and the ref that must have signed, held by the workflow test. The
release path is proved by test and by a hand-started run, and its tag path
waits for the first `v*` tag. What comes next is the owner's to decide.

### Housekeeping — the Dependabot backlog (brief, 2026-11-20)

Six Dependabot pull requests are open: #57, #59, #60, #61, #62 and #63, at
least three naming an advisory. Each is behind `main`, and `gate` is strict,
so merging them one by one costs six rounds of updating and waiting. One
branch takes them all.

**Decided:**
1. **Step 0.** Confirm `main`'s push run 44798857512 on `91f62fb` by id. Read
   the failed log of Dependabot's npm update job for `/frontend` (run
   44715925208) and attribute it in the report. Change nothing in `frontend`
   in this run; if the log names an advisory, raise it as a question.
2. **For each of the six, in number order,** merge its head into the branch,
   signed (`git merge --no-ff -S`), so Dependabot's own commit lands and
   GitHub closes the pull request as merged.
   - A conflict can only be in a lockfile. Abort that merge, and re-lock that
     one package at the pull request's version with the project's own tool
     (`uv lock --upgrade-package NAME==VERSION`, or `go get MODULE@VERSION`
     then `go mod tidy`), in a signed commit naming the pull request.
   - Never edit a lockfile by hand. Nothing moves but what each bump requires.
3. **Gates:** `just lint`, `just typecheck`, `just test` and `just cli-test`,
   one at a time, in the foreground. In CI, the fault library's `results.json`
   is unchanged.
4. **Report** which pull requests merged by their head and which were
   re-locked, and any bump that changed a test result.

**Do NOT:**
- bump anything Dependabot did not propose, or touch `frontend`;
- close a Dependabot pull request by hand;
- publish, release or deploy anything, or touch the ruleset.

---

## §4. Out of scope

- A merge queue.
- Required reviews from another person.
- Deploying.
- Registering the mark or the copyright.
- A light theme for the dashboard.
- Committing third-party reference images.
