"""Seed postmortem fixtures for Phase 6's RAG corpus.

Fixture data only — no UI for writing postmortems exists or is in scope
(see docs/IMPLEMENTATION_PLAN.md Phase 6). Eight postmortems, written as
real incident writeups (not one-liners) so semantic retrieval over their
embeddings has something real to match against, covering the three
fault-injector patterns from Phase 2 (demo-services/fault_cli.py) that
Phase 6's verification exercises: an isolated latency spike, an isolated
error burst, and a cascading failure across services — plus enough
variety (different services, a non-fault business-logic incident, an
unrelated-anomalies incident) that retrieval has to discriminate, not
just match on "something went wrong."

Loaded only by worker/scripts/seed_postmortems.py (the one-off embedding
backfill script) — never imported by app/rag/job.py itself, so a bug in
this fixture data can't affect the live retrieval path's imports.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedPostmortem:
    title: str
    body: str


SEED_POSTMORTEMS: list[SeedPostmortem] = [
    SeedPostmortem(
        title="Inventory-service latency spike from a slow stock lookup",
        body=(
            "Summary: inventory-service's p99 request duration (demo.http.server.duration) "
            "rose from a baseline of roughly 40ms to over 900ms for a 25-minute window. No "
            "requests failed outright and order-service continued to complete orders "
            "throughout, just slowly.\n\n"
            "Timeline: the first elevated duration samples appeared on the /reserve endpoint "
            "at 14:02. demo.http.server.requests stayed flat for inventory-service across the "
            "window, ruling out a traffic spike as the cause. order-service's own duration "
            "metric rose in step, lagging inventory-service by a few seconds each time, "
            "consistent with order-service simply waiting on a slow downstream call rather "
            "than doing more work itself.\n\n"
            "Root cause: a synchronous stock-lookup path in inventory-service was holding a "
            "lock per SKU for the full duration of the reservation, and a burst of repeated "
            "reservations against the same handful of SKUs serialized behind each other. "
            "Nothing crashed and nothing returned an error — the lock just made every request "
            "behind the first one wait its turn.\n\n"
            "Resolution: reducing the lock's scope from per-SKU-for-the-whole-request to "
            "per-SKU-for-the-decrement-only restored p99 to baseline within one deploy. "
            "Action item: alert on inventory-service duration specifically, not just its "
            "error rate — this incident produced zero errors and would have been invisible "
            "to an error-rate-only monitor."
        ),
    ),
    SeedPostmortem(
        title="Payments-service error burst from a bad validation deploy",
        body=(
            "Summary: payments-service's error rate (demo.http.server.errors on POST "
            "/charge) jumped from near-zero to roughly 60% of requests within two minutes of "
            "a deploy, and stayed there until rolled back 18 minutes later.\n\n"
            "Timeline: the deploy at 09:14 shipped a new amount-validation check. Almost "
            "immediately, demo.http.server.errors on payments-service climbed sharply while "
            "demo.http.server.duration stayed at baseline — these were fast failures, not "
            "slow ones. order-service logged a wave of \"order %s failed: payments-service "
            "unavailable\" entries as its calls to /charge came back with 5xx.\n\n"
            "Root cause: the new validation check rejected any amount with more than two "
            "decimal places after floating-point rounding introduced a third — a bug in the "
            "check itself, not in the amounts being charged. Every legitimate charge above a "
            "certain fractional-cent pattern started failing.\n\n"
            "Resolution: rolled back the deploy at 09:32; error rate returned to baseline "
            "within one export interval. Action item: this class of bug (a broken validation "
            "rule rejecting valid input) produces a very clean, sudden error-rate step "
            "function with no duration change — a distinctive enough signature that it's "
            "worth training incident responders to recognize on sight rather than always "
            "reaching for logs first."
        ),
    ),
    SeedPostmortem(
        title="Cascading failure: inventory-service latency spike caused order-service timeouts",
        body=(
            "Summary: a latency spike in inventory-service's /reserve endpoint pushed "
            "response times past order-service's fixed downstream timeout, which turned a "
            "pure latency problem in one service into a hard error-rate problem in another. "
            "order-service's error rate rose within seconds of inventory-service's duration "
            "climbing, and both anomalies fell inside the same correlation window.\n\n"
            "Timeline: inventory-service demo.http.server.duration crossed several seconds "
            "per request starting at 16:47. order-service calls its downstream inventory "
            "check with a fixed timeout shorter than a plausible slow-downstream response, "
            "specifically so a hung dependency becomes a fast, visible failure instead of a "
            "silent hang — but that same design meant every order in the window failed. "
            "order-service's logs filled with \"order %s failed: inventory-service "
            "unavailable: <timeout>\" and its own demo.http.server.errors metric spiked in "
            "lockstep, one to two seconds after each inventory-service duration sample.\n\n"
            "Root cause: inventory-service itself was slow (a downstream dependency of its "
            "own had degraded), and order-service's timeout — while correctly configured to "
            "fail fast rather than hang — had no fallback path, so every slow reservation "
            "became a failed order rather than a slow-but-successful one.\n\n"
            "Resolution: inventory-service's upstream dependency recovered on its own after "
            "12 minutes; order-service's error rate recovered immediately once inventory-"
            "service's duration dropped back below the timeout. Action item: the fact that "
            "inventory-service's anomaly (duration) and order-service's anomaly (errors) are "
            "different metric types is exactly the signature of a cascading failure across a "
            "service boundary, not two independent problems — when order-service's error "
            "logs cite \"inventory-service unavailable\" and inventory-service's own duration "
            "metric was already anomalous moments earlier, that's the causal direction, not a "
            "coincidence."
        ),
    ),
    SeedPostmortem(
        title="Order-service errors from a full payments-service outage",
        body=(
            "Summary: payments-service became completely unreachable (connection refused, "
            "not merely slow) for 6 minutes, and order-service's error rate on /orders rose "
            "to match, with every failure attributable to the payments call rather than the "
            "inventory call.\n\n"
            "Timeline: payments-service's own request-count metric (demo.http.server."
            "requests) dropped to zero at 11:05 — it wasn't processing anything, successfully "
            "or not, because the process had crashed. order-service's logs showed \"order %s "
            "failed: payments-service unavailable\" exclusively; no \"inventory-service "
            "unavailable\" entries appeared in the same window, which is what distinguishes "
            "this from an inventory-driven cascade.\n\n"
            "Root cause: an unhandled exception during payments-service startup after a "
            "config reload crashed the process; the orchestrator's restart backoff meant it "
            "stayed down for several minutes before recovering on its own.\n\n"
            "Resolution: process auto-restarted and recovered without manual intervention. "
            "Action item: order-service's error message already names which downstream "
            "dependency it was calling when a request failed — that single log field is "
            "usually enough to tell a payments-driven cascade from an inventory-driven one "
            "without needing to correlate metrics from both services by hand."
        ),
    ),
    SeedPostmortem(
        title="Inventory-service stockout driving elevated order-service 409s",
        body=(
            "Summary: this incident looked like an anomaly at a glance — a sustained rise in "
            "4xx responses from inventory-service's /reserve endpoint — but the cause was "
            "entirely expected business behavior, not a fault. A single popular SKU sold "
            "through its available stock during a short promotional spike.\n\n"
            "Timeline: inventory-service began logging \"insufficient stock for %s (requested "
            "%d, have %d)\" repeatedly starting at 13:00, and returning 409 to the matching "
            "reservation attempts. Duration stayed flat and payments-service was never "
            "invoked for the failed reservations, since order-service short-circuits before "
            "calling payments-service when the reservation step itself fails.\n\n"
            "Root cause: genuine stock depletion, not a latency or error-rate fault in the "
            "conventional sense. inventory-service's demo stock counter for that one SKU "
            "simply reached zero under real demand.\n\n"
            "Resolution: no code change; stock was replenished and 409s stopped. Action item: "
            "this is a useful negative example — a metric anomaly doesn't always indicate a "
            "service defect, and a 409-driven spike with flat duration and no matching "
            "payments-service impact should be weighted differently from a 5xx-driven one "
            "when suggesting root cause."
        ),
    ),
    SeedPostmortem(
        title="Payments-service latency spike from a slow upstream card-network call",
        body=(
            "Summary: payments-service's p99 duration on /charge rose to roughly 2.5 seconds "
            "for about 15 minutes, with error rate essentially unaffected — almost every "
            "request still succeeded, just slowly.\n\n"
            "Timeline: demo.http.server.duration on payments-service climbed starting at "
            "10:20. order-service's own duration rose in parallel, again lagging by a couple "
            "of seconds per request, the same downstream-wait signature seen in the "
            "inventory-service latency incident, just against a different downstream. No "
            "elevated error rate appeared anywhere in the chain — order-service's timeout was "
            "comfortably longer than payments-service's slow response in this case, so slow "
            "charges still completed rather than timing out.\n\n"
            "Root cause: payments-service's charge call depends on an external card-network "
            "simulator in this environment; that dependency itself was intermittently slow. "
            "Nothing in payments-service's own code was at fault.\n\n"
            "Resolution: resolved when the upstream dependency's latency returned to normal; "
            "no deploy needed on our side. Action item: this incident and the inventory-"
            "service latency spike incident produce a near-identical shape (a single "
            "service's duration rises, order-service's duration rises a few seconds later, no "
            "errors anywhere) — distinguishing them requires looking at which service's "
            "duration metric moved first, not just that a duration anomaly occurred."
        ),
    ),
    SeedPostmortem(
        title="Order-service isolated latency regression from a tracing change",
        body=(
            "Summary: order-service's own p99 duration on POST /orders rose by roughly "
            "300ms after a deploy, with no corresponding change in inventory-service or "
            "payments-service's metrics at all — an isolated, single-service regression.\n\n"
            "Timeline: the increase appeared immediately after a deploy at 08:41 that changed "
            "how trace context was propagated to downstream calls. inventory-service and "
            "payments-service's demo.http.server.duration stayed flat throughout; only "
            "order-service's own duration moved, and it moved uniformly across every request "
            "rather than in bursts.\n\n"
            "Root cause: the new propagation code was doing a redundant header-serialization "
            "pass on every outgoing call, adding fixed overhead to every request rather than "
            "affecting a subset of them.\n\n"
            "Resolution: reverted the change; duration returned to baseline immediately. "
            "Action item: a uniform, deploy-aligned duration shift confined to a single "
            "service — with its dependencies' metrics untouched — points at that service's "
            "own code, not at a downstream cause. This is the opposite signature from the "
            "cascading incidents in this corpus, where the anomaly in the calling service "
            "trails a few seconds behind an anomaly in the service it depends on."
        ),
    ),
    SeedPostmortem(
        title="Coincidental, unrelated anomalies in inventory-service and payments-service",
        body=(
            "Summary: inventory-service and payments-service both showed anomalous metrics "
            "within the same few minutes, which briefly looked like a single incident but "
            "turned out to be two unrelated problems that happened to overlap in time.\n\n"
            "Timeline: inventory-service's duration rose at 19:02 due to a one-off garbage-"
            "collection pause; independently, payments-service's error rate rose at 19:04 "
            "because of a transient DNS resolution failure reaching its card-network "
            "simulator. order-service showed no anomaly of its own — its calls to both "
            "downstreams stayed within its timeout, and it logged no \"unavailable\" errors "
            "for either dependency.\n\n"
            "Root cause: two independent, coincidental faults with no causal link between "
            "them. Neither service's fault caused or contributed to the other's.\n\n"
            "Resolution: both resolved on their own within a few minutes, and neither "
            "required a deploy. Action item: the absence of any order-service anomaly is the "
            "key signal here — a genuine cascade shows up as a *third* service's metric "
            "moving in response to the first two (as in the inventory-to-order and payments-"
            "outage incidents in this corpus); two anomalies with no connecting third signal "
            "should be treated as coincidental until something else ties them together."
        ),
    ),
]
