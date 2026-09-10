package model

import "time"

// The extractor plugin protocol and the capture bundle it rolls up into
// (Phase 28 fields 7, 8 and 9). The Go mirror of
// shared/culprit_model/protocol.py; the prose contract third parties
// read is docs/EXTRACTOR_PROTOCOL.md.

// ExtractorProtocolVersion is bumped only for a breaking change to the
// request/response shape. An extractor that does not understand the
// version it is handed must skip everything and say so, rather than
// answer a question it may be misreading.
const ExtractorProtocolVersion = 1

// Want names a class of fact an orchestrator can ask for.
type Want string

const (
	WantHTTPRoutes     Want = "http_routes"
	WantDBSchema       Want = "db_schema"
	WantConfigKeys     Want = "config_keys"
	WantClientCalls    Want = "client_calls"
	WantTestAssertions Want = "test_assertions"
	// WantDependencies is a sixth beyond field 7's five, because
	// acceptance criterion 1 requires dependency versions and the five
	// had no home for them. Recorded as a plan correction rather than
	// quietly folded into db_schema.
	WantDependencies Want = "dependencies"
)

// AllWants is what `culprit intent` asks for when the user does not
// narrow it.
var AllWants = []Want{
	WantHTTPRoutes,
	WantDBSchema,
	WantConfigKeys,
	WantClientCalls,
	WantTestAssertions,
	WantDependencies,
}

// Predicates this phase's extractors emit. Fact.Predicate stays a plain
// string: D7 says the comparator knows nothing about HTTP, SQL or auth,
// and closing the vocabulary here would make adding a fault class an
// engine change.
const (
	PredicateExists         = "exists"
	PredicateRequestSchema  = "request_schema"
	PredicateResponseSchema = "response_schema"
	PredicateStatusCodes    = "status_codes"
	PredicateColumns        = "columns"
	PredicateColumnType     = "column_type"
	PredicateNullable       = "nullable"
	PredicateMigrationHead  = "migration_head"
	PredicateVersion        = "version"
	PredicateReadBy         = "read_by"
	// PredicateValueShape is kept as a name a third-party extractor
	// may use, but nothing in this repository emits it any more.
	//
	// It was one predicate carrying two different claims, and Phase 29
	// found the resulting false positive on Culprit's own repository:
	// `.env.example` said AGENT_AUTOMATION_TOKEN had shape
	// string/opaque/medium, `api/app/auth/config.py` said
	// string/not_applicable/empty, and the comparator dutifully
	// reported that they disagreed. They did not. One is the shape of a
	// *placeholder committed as an example*, the other the shape of a
	// *default the code falls back to*, and a key can perfectly well
	// have a long opaque example and an empty default. Comparison is by
	// (subject, predicate), so two claims that are not the same claim
	// must not share a predicate name.
	PredicateValueShape   = "value_shape"
	PredicateExampleShape = "example_shape"
	PredicateDefaultShape = "default_shape"
	PredicateRequired     = "required"
	PredicateCalls        = "calls"
	// PredicateExercisedByTest is "a test exercises this route",
	// deliberately not "and expects this status". See the Python
	// extractor's extract_test_assertions for the three false
	// positives on this repository that settled it.
	PredicateExercisedByTest = "exercised_by_test"
)

// Skip is one thing an extractor was asked for and could not provide.
//
// Reason is required and free text, because the reader of a report is a
// human deciding whether the gap matters. This is the honesty rule that
// makes the whole orchestration safe: an extractor that cannot answer
// says so and exits zero, and a missing extractor degrades the report
// instead of breaking the run.
type Skip struct {
	Want   string `json:"want"`
	Reason string `json:"reason"`
	// Component is which component the gap is in. Filled in by the
	// orchestrator, because only it knows: a report listing "no
	// .env.example found" three times with no way to tell which of three
	// services each line is about is a report nobody can act on. Found
	// by running the command against this repo's own demo services.
	Component string `json:"component,omitempty"`
	Extractor string `json:"extractor,omitempty"`
}

// ExtractorRequest is what the orchestrator writes to an extractor's
// stdin (field 7).
type ExtractorRequest struct {
	Protocol int    `json:"protocol"`
	Root     string `json:"root"`
	Want     []Want `json:"want"`
	// Environment is null for an INTENT extraction. Present only once
	// environment capture exists (Phase 30) — extractors in this phase
	// are handed null and must not go looking for a live system.
	Environment *string `json:"environment"`
	// Component is not in field 7's literal shape and is required in
	// practice: every subject URI needs a component name, and an
	// extractor cannot invent one that will match the system model.
	// Recorded as a plan correction.
	Component string `json:"component,omitempty"`
}

// ExtractorResponse is what an extractor writes to stdout (field 7):
// exactly one object.
type ExtractorResponse struct {
	Protocol int `json:"protocol"`
	// Extractor is "name@version", e.g. "culprit-extract-python@0.1.0".
	// It ends up in every fact's provenance, which is what makes a wrong
	// fact traceable to the thing that got it wrong.
	Extractor string `json:"extractor"`
	Facts     []Fact `json:"facts"`
	Skipped   []Skip `json:"skipped"`
}

// CaptureBundle is one extraction run, whole: what was asked, what came
// back, and what did not.
//
// This is the artefact §5 promises is safe to attach to a bug report,
// and the body POST /facts/captures accepts. Its safety is not a review
// convention — every Fact inside it has already refused to carry an
// ungranted config value, so marshalling the bundle cannot produce one.
type CaptureBundle struct {
	Protocol    int        `json:"protocol"`
	Plane       Plane      `json:"plane"`
	Environment *string    `json:"environment"`
	Extractor   string     `json:"extractor"`
	CaptureID   string     `json:"capture_id"`
	StartedAt   time.Time  `json:"started_at"`
	FinishedAt  *time.Time `json:"finished_at,omitempty"`
	Facts       []Fact     `json:"facts"`
	Skipped     []Skip     `json:"skipped"`
	// Meta is free-form, non-secret run context — the source root, the
	// component names looked at, the CLI version. Never config values.
	Meta map[string]string `json:"meta,omitempty"`
	// Grants and Refused are Phase 30's field 7: "a capture is a signed,
	// timestamped bundle of CONFIGURED facts plus the grant set that
	// produced it, so a reader can tell what was *not* looked at".
	//
	// Both omitted for an INTENT capture, which reads no environment and
	// so exercises no capability — that keeps every Phase 28 golden
	// bundle byte-identical.
	Grants  []Grant   `json:"grants,omitempty"`
	Refused []Refusal `json:"refused,omitempty"`
}

// Grant is one capability the capture ran under (§2.7), with the
// allowlist for the capabilities that take one.
//
// Recorded whether or not it was used: the question a reader of a
// bug-report attachment is asking is "what was this tool *allowed* to
// look at", and a grant that was never exercised is part of the answer.
type Grant struct {
	Capability string   `json:"capability"`
	Allow      []string `json:"allow,omitempty"`
	Used       bool     `json:"used"`
}

// Refusal is one check that did not happen because the capability it
// needs was not granted — §2.6's `refused` verdict, for a capture.
//
// A refusal is never an omission. "I could not check X because you have
// not granted Y" is a feature of the report, and the alternative — a
// fact that is simply not there — reads as "nothing wrong with X".
//
// Every field is built from closed vocabulary or from names the manifest
// declares (a capability, a component, a check name). Never from an
// error message, and never from anything the environment returned:
// standing invariant 11 says error text is output, and the only way to
// be sure a reason cannot carry a value is to never build one from text
// the tool did not write.
type Refusal struct {
	Capability string `json:"capability"`
	Component  string `json:"component,omitempty"`
	Check      string `json:"check"`
	Reason     string `json:"reason"`
}

// SkipsFromFailure turns one extractor failure into a skip per requested
// want.
//
// Per want, not one aggregate: the report says what is missing, and
// "http_routes and config_keys are missing because the extractor is not
// installed" is a different sentence from "something went wrong".
func SkipsFromFailure(extractor string, wants []string, reason string) []Skip {
	skips := make([]Skip, 0, len(wants))
	for _, want := range wants {
		skips = append(skips, Skip{Want: want, Reason: reason, Extractor: extractor})
	}
	return skips
}
