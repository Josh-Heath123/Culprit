# Demonstration video — script

About six minutes, in `docs/PRODUCTISATION.md` §7's five parts. The author reads
the narration; everything on screen is a real run (see
[`checklist.md`](checklist.md)), and [`storyboard.md`](storyboard.md) says
what is on screen for each line. Nothing here shows a feature that does not
work: if a line below stops being true, cut the line, not the check.

---

## Part 1 — Introduction (0:00–0:45)

> Most production faults aren't a bug in one service. They're a
> disagreement between two things that were each fine on their own — the
> frontend calls a route the API stopped serving; the code reads a key
> production never set; a token is minted for the wrong audience.
>
> Each half passes review. The fault is the gap between them, and nobody
> owns the gap.
>
> Culprit finds those gaps. It's built for small teams running a handful of
> services without an SRE: the people who find these faults today by
> reading logs after a customer does.

## Part 2 — Application walkthrough (0:45–3:15)

**`culprit check` (0:45–1:25)**

> Culprit reads what a repository says about itself — the routes the API
> serves, the calls the frontend makes, the columns the ORM maps, the
> migrations, the config keys — and compares them. Here it is on a small
> demo system with faults planted in it.
>
> Each finding has both sides' evidence: which file, which line, which
> extractor, and a severity worked out from the service graph — this one
> is on the request path, so it breaks requests. And it lists what it could
> not check, rather than letting silence read as "fine".
>
> It runs in CI with no agent, no telemetry and no account, and writes
> SARIF, so findings land on the changed lines of a pull request.

**`culprit env capture` and `diff` (1:25–1:55)**

> An environment is the second source. Capture reads what production is
> actually set up with — and records the shape of each value, never the
> value, unless you grant it. Diff compares environments with each other
> and with the code: production is missing a key the code reads.

**`culprit diagnose` and the dashboard (1:55–3:15)**

> The quickstart has injected a real fault: order-service's token for
> inventory-service was minted for the wrong audience, so placing an order
> fails with a 502.
>
> `culprit diagnose` walks the system from that symptom. It bisects the
> request path, runs only the probes that can tell one hypothesis from
> another, and stops at the boundary it can prove.
>
> In the dashboard, the root is marked: the audience on that connection.
> Every edge in the tree opens to the readings that established it — here,
> the token's audience is "inventory", not "inventory-service".
>
> There's no confidence score. There are four checks: was it reproduced,
> were the alternatives ruled out, was it compared against a working
> environment, and was a fix verified. Two hold here, and the page says why
> the other two don't.
>
> And when the walk can't finish — here, it wasn't granted the token to
> read — it says where it stopped and what it couldn't check. It never
> calls that a cause.

## Part 3 — Technical overview (3:15–4:45)

> Three planes of truth: what the system is meant to do, read from the
> repository; what an environment is configured to do; and what actually
> happens when you ask it. Divergence between them is the finding.
>
> Everything is a fact about a subject, and two sources that describe the
> same thing produce the identical subject — in Go, Python and Node, held
> together by shared conformance fixtures — so comparing is a grouping,
> not a guess. The comparator knows nothing about HTTP or SQL: a new kind
> of fault is a new extractor or probe, never an engine change.
>
> The CLI is one static Go binary. Probes are read-only and ask a
> capability ledger before they dial anything; a timeout is
> "inconclusive", never "fail". Language-specific extraction runs as
> plugins over JSON on stdin and stdout.
>
> None of it calls a language model, and CI enforces that structurally: the
> check pipeline links no networking package at all.
>
> The control plane is FastAPI, Postgres with TimescaleDB, and Redis. Each
> writer has its own least-privilege database role — fourteen of them — and
> the database itself refuses a fault-tree edge that cites no reading.
> The React dashboard is end-to-end tested in CI against the same stack the
> quickstart builds.

## Part 4 — Setup (4:45–5:35)

> To try it: clone the repository and run `just quickstart`. It needs only
> Docker and `just`. It generates every secret, runs the migrations, starts
> the stack and three demo services, injects that fault, diagnoses it, and
> prints the address of the investigation and an admin login. No API key of
> any kind.
>
> For the CLI alone: Go, `uv` and Node, then `just cli-build`, and
> `culprit check` on your own repository with a `culprit.yaml` describing
> its components.

## Part 5 — Conclusion (5:35–6:00)

> Culprit turns "it works on my side" into a list of contradictions, each
> with its evidence — before deploy, and in production when something
> breaks. Deterministic, read-only, and honest about what it couldn't
> check.
