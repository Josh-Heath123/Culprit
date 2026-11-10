package verify

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// ---- a world that can be changed ----------------------------------------------

// world is what each probe sees now, keyed by reading id's target; a test
// changes it between diagnosis and verification, which is the fix.
// Runs are counted per target, across readings: r2 and r3 share one, so
// the first round takes two entries before the second round starts.
type world map[string][]model.Verdict // target -> verdicts, one per run, last repeats

type countingRunner struct {
	world world
	runs  map[string]int // target -> runs so far
	total int
}

var clock = time.Date(2026, 11, 10, 12, 0, 0, 0, time.UTC)

func (r *countingRunner) Run(_ context.Context, request Request) model.Reading {
	r.total++
	sequence := r.world[request.Target]
	verdict := sequence[min(r.runs[request.Target], len(sequence)-1)]
	r.runs[request.Target]++
	reading := model.Reading{
		ProbeID: request.ProbeID, ProbeVersion: 1, Target: request.Target,
		Environment: request.Environment, Verdict: verdict,
		// A run is stamped with when it ran, and by whom: a stored reading
		// handed back would carry the investigation's stamp instead.
		TakenAt: clock.Add(time.Duration(r.total) * time.Second), AgentID: "verify-runner",
	}
	if verdict.NeedsReason() {
		reading.Reason = "the simulated world gives no reason"
	}
	return reading
}

const (
	healthy = "component:inventory-service"
	stock   = "http:inventory-service/GET /stock"
	env     = "faults-order"
)

// investigation is the contract fault, diagnosed: inventory-service is up
// (r1 passes), its stock route is gone (r2 fails, and r3 reproduces it).
func investigation() (model.Investigation, Record) {
	at := clock.Add(-time.Hour)
	reading := func(probe, target string, verdict model.Verdict) model.Reading {
		return model.Reading{ProbeID: probe, ProbeVersion: 1, Target: target, Environment: env,
			Verdict: verdict, TakenAt: at, AgentID: "diagnosis"}
	}
	inv := model.Investigation{
		ID: "inv-test", OpenedAt: at, Environment: env,
		Symptom: model.Symptom{Kind: model.SymptomComponent, Subject: "component:order-service", Source: "test",
			Attestation: model.Attestation{Kind: model.AttestedReported, ReportedBy: "test"}},
		Readings: []model.InvestigationReading{
			{ID: "r1", Reading: reading("probe.http.reachable", healthy, model.VerdictPass)},
			{ID: "r2", Reading: reading("probe.http.route_conformance", stock, model.VerdictFail)},
			{ID: "r3", Reading: reading("probe.http.route_conformance", stock, model.VerdictFail)},
		},
	}
	record := Record{Version: RecordVersion, InvestigationID: inv.ID, Environment: env,
		Vantage: "order-service", BeforeCapture: "cap-before"}
	for _, item := range inv.Readings {
		record.Requests = append(record.Requests, Request{ReadingID: item.ID, ProbeID: item.Reading.ProbeID,
			Target: item.Reading.Target, Environment: env, Inputs: map[string]any{"url": "http://inventory-service:8002"}})
	}
	return inv, record
}

// capture is order-service's environment as a process capture records it:
// each key's existence and shape.
func capture(id string, keys ...string) *model.CaptureBundle {
	name := env
	bundle := &model.CaptureBundle{Plane: model.PlaneConfigured, Environment: &name, CaptureID: id, StartedAt: clock}
	provenance := model.Provenance{SourceKind: model.SourceIntrospection, Extractor: "culprit@test",
		ConfidenceRank: model.RankRuntimeIntrospection}
	for _, entry := range keys {
		component, key, _ := strings.Cut(entry, "/")
		subject := model.MustBuildSubject(model.KindConfig, model.Parts{"component": component, "key": key})
		shape := model.ShapeOfString("a-value")
		bundle.Facts = append(bundle.Facts,
			model.Fact{Plane: model.PlaneConfigured, Subject: subject, Predicate: model.PredicateExists, Value: true,
				Environment: env, Provenance: provenance, CapturedAt: clock, CaptureID: id},
			model.Fact{Plane: model.PlaneConfigured, Subject: subject, Predicate: model.PredicateValueShape,
				ValueShape: &shape, Environment: env, Provenance: provenance, CapturedAt: clock, CaptureID: id})
	}
	return bundle
}

var orderKeys = []string{"order-service/INVENTORY_SERVICE_URL", "order-service/INVENTORY_TOKEN"}

type scenario struct {
	world   world
	changes []model.Change
	before  *model.CaptureBundle
	after   *model.CaptureBundle
	record  func(*Record)
}

func verifyIn(t *testing.T, s scenario) (model.Verification, *countingRunner) {
	t.Helper()
	inv, record := investigation()
	if s.record != nil {
		s.record(&record)
	}
	runner := &countingRunner{world: s.world, runs: map[string]int{}}
	verification, err := Run(context.Background(), Options{
		ID: "ver-test", Investigation: inv, Record: record, Changes: s.changes,
		Before: s.before, After: s.after, Runner: runner, Now: func() time.Time { return clock },
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := verification.Validate(); err != nil {
		t.Fatalf("verify built a verification the model rejects: %v", err)
	}
	if strings.Contains(verification.Reason, "->") {
		t.Errorf("the reason contains an arrow pair: %s", verification.Reason)
	}
	return verification, runner
}

var (
	fixed      = world{healthy: {model.VerdictPass}, stock: {model.VerdictPass}}
	notFixed   = world{healthy: {model.VerdictPass}, stock: {model.VerdictFail}}
	contractFx = []model.Change{{Kind: model.ChangeConfig, Subject: "config:inventory-service/CONTRACT_FAULT"}}
)

func unchanged() (*model.CaptureBundle, *model.CaptureBundle) {
	return capture("cap-before", orderKeys...), capture("cap-after", orderKeys...)
}

// TestEveryReadingIsMeasuredAgainTwiceAndNoneIsReused is the count the
// criterion asserts: exactly the investigation's readings, each run twice,
// every run a fresh measurement.
func TestEveryReadingIsMeasuredAgainTwiceAndNoneIsReused(t *testing.T) {
	before, after := unchanged()
	verification, runner := verifyIn(t, scenario{world: fixed, changes: contractFx, before: before, after: after})
	inv, _ := investigation()
	if runner.total != 2*len(inv.Readings) {
		t.Fatalf("%d probe runs for %d readings; want each twice (%d)", runner.total, len(inv.Readings), 2*len(inv.Readings))
	}
	if len(verification.Reran) != len(inv.Readings) {
		t.Fatalf("%d re-runs recorded for %d readings", len(verification.Reran), len(inv.Readings))
	}
	stamps := map[time.Time]bool{}
	for index, rerun := range verification.Reran {
		if rerun.ReadingID != inv.Readings[index].ID || rerun.Was != inv.Readings[index].Reading.Verdict {
			t.Errorf("re-run %d is %s (was %s); want %s (was %s)", index, rerun.ReadingID, rerun.Was,
				inv.Readings[index].ID, inv.Readings[index].Reading.Verdict)
		}
		for _, run := range rerun.Runs {
			if run.AgentID != "verify-runner" || stamps[run.TakenAt] {
				t.Errorf("re-run of %s holds a reading that was not measured now: %+v", rerun.ReadingID, run)
			}
			stamps[run.TakenAt] = true
		}
	}
	if verification.Verdict != model.VerificationVerified {
		t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
	}
}

func TestTheVerdicts(t *testing.T) {
	before, after := unchanged()
	cases := []struct {
		name    string
		s       scenario
		verdict model.VerificationVerdict
		says    string
	}{
		{"the fix fixed it", scenario{world: fixed, changes: contractFx, before: before, after: after},
			model.VerificationVerified, "nothing the capture records changed"},
		{"a wrong fix", scenario{world: notFixed, changes: contractFx, before: before, after: after},
			model.VerificationNotResolved, "still failing on both runs: probe.http.route_conformance"},
		{"a fix that breaks what passed",
			scenario{world: world{healthy: {model.VerdictFail}, stock: {model.VerdictPass}}, changes: contractFx, before: before, after: after},
			model.VerificationRegressed, "passed before and fail now: probe.http.reachable on component:inventory-service (r1)"},
		{"an unrelated change underneath",
			scenario{world: fixed, changes: contractFx, before: before,
				after: capture("cap-after", append([]string{"order-service/FEATURE_FLAG"}, orderKeys...)...)},
			model.VerificationChangedUnderneath, "config:order-service/FEATURE_FLAG (exists)"},
		{"a key removed underneath",
			scenario{world: fixed, changes: contractFx, before: before, after: capture("cap-after", orderKeys[0])},
			model.VerificationChangedUnderneath, "config:order-service/INVENTORY_TOKEN"},
		{"the change named explains the difference",
			scenario{world: fixed, changes: []model.Change{{Kind: model.ChangeConfig, Subject: "config:order-service/FEATURE_FLAG"}},
				before: before, after: capture("cap-after", append([]string{"order-service/FEATURE_FLAG"}, orderKeys...)...)},
			model.VerificationVerified, "explained by config:order-service/FEATURE_FLAG"},
		{"a result that flips",
			scenario{world: world{healthy: {model.VerdictPass}, stock: {model.VerdictPass, model.VerdictPass, model.VerdictFail}}, changes: contractFx, before: before, after: after},
			model.VerificationInconclusive, "was pass, then fail"},
		{"a probe refused now",
			scenario{world: world{healthy: {model.VerdictRefused}, stock: {model.VerdictPass}}, changes: contractFx, before: before, after: after},
			model.VerificationInconclusive, "was refused"},
		{"no change named", scenario{world: fixed, before: before, after: after},
			model.VerificationInconclusive, "no change was named"},
		{"no record of before",
			scenario{world: fixed, changes: contractFx, record: func(r *Record) {
				r.BeforeCapture, r.BeforeAbsent = "", "the grants for faults-order allow no capture"
			}},
			model.VerificationInconclusive, "no record of the environment before"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			verification, _ := verifyIn(t, testCase.s)
			if verification.Verdict != testCase.verdict {
				t.Fatalf("verdict %s, want %s: %s", verification.Verdict, testCase.verdict, verification.Reason)
			}
			if !strings.Contains(verification.Reason, testCase.says) {
				t.Errorf("the reason does not say %q: %s", testCase.says, verification.Reason)
			}
		})
	}
}

// TestASameShapedValueChangeIsNotADifference: captures hold names and
// shapes, so a value changed to another of the same shape is not seen.
// That is a limit (docs/LIMITS.md), written down here so it stays known.
func TestASameShapedValueChangeIsNotADifference(t *testing.T) {
	before, after := unchanged()
	if differences := Differences(*before, *after); len(differences) != 0 {
		t.Fatalf("two captures of the same keys and shapes differ: %v", differences)
	}
	changed := capture("cap-after", orderKeys...)
	shape := model.ShapeOfString("")
	changed.Facts[1].ValueShape = &shape
	differences := Differences(*before, *changed)
	if len(differences) != 1 || differences[0].Predicate != model.PredicateValueShape {
		t.Fatalf("a key whose shape changed: %v", differences)
	}
}

func TestARecordThatDoesNotMatchItsInvestigationIsRefused(t *testing.T) {
	inv, good := investigation()
	before, after := unchanged()
	for name, spoil := range map[string]func(*Record){
		"a reading with no request": func(r *Record) { r.Requests = r.Requests[:2] },
		"a request for another probe": func(r *Record) {
			r.Requests[1].ProbeID = "probe.http.reachable"
		},
		"another investigation's record": func(r *Record) { r.InvestigationID = "inv-other" },
		"neither a before nor why not":   func(r *Record) { r.BeforeCapture = "" },
		"a newer record":                 func(r *Record) { r.Version = RecordVersion + 1 },
	} {
		t.Run(name, func(t *testing.T) {
			record := good
			record.Requests = append([]Request(nil), good.Requests...)
			spoil(&record)
			runner := &countingRunner{world: fixed, runs: map[string]int{}}
			_, err := Run(context.Background(), Options{ID: "ver-test", Investigation: inv, Record: record,
				Changes: contractFx, Before: before, After: after, Runner: runner})
			if err == nil {
				t.Fatal("verified against a record that does not match")
			}
			if runner.total != 0 {
				t.Errorf("%d probes ran before the record was refused", runner.total)
			}
		})
	}
}

func TestTheCaptureBeforeMustBeTheOneRecorded(t *testing.T) {
	inv, record := investigation()
	_, err := Run(context.Background(), Options{ID: "ver-test", Investigation: inv, Record: record,
		Changes: contractFx, Before: capture("cap-other", orderKeys...), After: capture("cap-after", orderKeys...),
		Runner: &countingRunner{world: fixed, runs: map[string]int{}}})
	if err == nil || !strings.Contains(err.Error(), "cap-before") {
		t.Fatalf("a different capture before was accepted: %v", err)
	}
}
