package capability

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func yes() *bool { value := true; return &value }
func no() *bool  { value := false; return &value }

func TestParseAcceptsTheSection27Vocabulary(t *testing.T) {
	grants, err := Parse(map[string]Raw{
		"config.read.names":  {Enabled: yes()},
		"config.read.values": {Items: []string{"orders-api/LOG_LEVEL"}},
		"db.metadata.read":   {Enabled: yes()},
		"net.dns.resolve":    {Enabled: no()},
	})
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if !grants.Has(ConfigReadNames) || !grants.Has(DBMetadataRead) {
		t.Error("a granted capability is not reported as granted")
	}
	if grants.Has(NetDNSResolve) {
		t.Error("`false` granted the capability")
	}
	if !grants.Allows(ConfigReadValues, "orders-api/LOG_LEVEL") {
		t.Error("an allowlisted key is not allowed")
	}
	if grants.Allows(ConfigReadValues, "orders-api/DATABASE_URL") {
		t.Error("a key that is not on the allowlist is allowed")
	}
}

func TestParseRefuses(t *testing.T) {
	for _, testCase := range []struct {
		name  string
		raw   map[string]Raw
		wants string
	}{
		{"a write capability", map[string]Raw{"db.schema.write": {Enabled: yes()}}, "no write capability"},
		{"a typo", map[string]Raw{"config.read.name": {Enabled: yes()}}, "not a capability"},
		{"a blanket value grant", map[string]Raw{"config.read.values": {Enabled: yes()}}, "explicit list"},
		{"an empty allowlist", map[string]Raw{"process.exec.allowlist": {Items: []string{}}}, "grants nothing"},
		{"a wildcard", map[string]Raw{"config.read.values": {Items: []string{"orders-api/*"}}}, "wildcards"},
		{"a list where a bool belongs", map[string]Raw{"db.metadata.read": {Items: []string{"x"}}}, "true or false"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			_, err := Parse(testCase.raw)
			if err == nil || !strings.Contains(err.Error(), testCase.wants) {
				t.Fatalf("expected a refusal mentioning %q, got %v", testCase.wants, err)
			}
		})
	}
}

// TestAnUngrantedCheckIsRefusedNotOmitted is field 13's "grant-enforcement
// tests asserting `refused` rather than silent omission", at the unit
// level: every denied Require leaves exactly one refusal behind.
func TestAnUngrantedCheckIsRefusedNotOmitted(t *testing.T) {
	grants, _ := Parse(map[string]Raw{"config.read.names": {Enabled: yes()}})
	ledger := NewLedger(grants)

	if !ledger.Require(ConfigReadNames, "orders-api", "environment variables") {
		t.Fatal("a granted capability was refused")
	}
	if ledger.Require(DBMetadataRead, "orders-api", "live schema") {
		t.Fatal("an ungranted capability was allowed")
	}
	// Asked twice: still one line in the report, not two.
	ledger.Require(DBMetadataRead, "orders-api", "live schema")

	refused := ledger.Refusals()
	if len(refused) != 1 {
		t.Fatalf("expected exactly one refusal, got %+v", refused)
	}
	if refused[0].Capability != string(DBMetadataRead) || refused[0].Component != "orders-api" {
		t.Errorf("the refusal does not say what was refused: %+v", refused[0])
	}

	records := ledger.Records()
	if len(records) != 1 || !records[0].Used || records[0].Capability != string(ConfigReadNames) {
		t.Errorf("the grant record does not say config.read.names was granted and used: %+v", records)
	}
}

func TestAnUnlistedKeyIsRefusedByName(t *testing.T) {
	grants, _ := Parse(map[string]Raw{
		"config.read.values": {Items: []string{"orders-api/LOG_LEVEL"}},
	})
	ledger := NewLedger(grants)
	if !ledger.RequireItem(ConfigReadValues, "orders-api/LOG_LEVEL", "orders-api", "value of LOG_LEVEL") {
		t.Fatal("an allowlisted key was refused")
	}
	if ledger.RequireItem(ConfigReadValues, "orders-api/DATABASE_URL", "orders-api", "value of DATABASE_URL") {
		t.Fatal("an unlisted key was allowed")
	}
	refused := ledger.Refusals()
	if len(refused) != 1 || !strings.Contains(refused[0].Reason, "not for orders-api/DATABASE_URL") {
		t.Errorf("expected the unlisted key to be refused by name, got %+v", refused)
	}
}

func TestEveryCapabilityInTheListIsKnown(t *testing.T) {
	// §2.7, copied out by hand. If a capability is added to the plan and
	// not here, or removed here and not from the plan, this says so.
	for _, name := range []string{
		"model.read", "repo.read", "config.read.names", "config.read.values",
		"db.metadata.read", "db.rows.read", "net.dns.resolve", "net.tcp.connect",
		"net.tls.inspect", "net.http.outbound", "telemetry.logs.read",
		"telemetry.metrics.read", "telemetry.traces.read", "deploy.metadata.read",
		"process.exec.allowlist",
	} {
		if !Known(name) {
			t.Errorf("%s is in §2.7 and unknown here", name)
		}
	}
	for name := range known {
		if strings.HasSuffix(string(name), ".write") {
			t.Errorf("%s: no write capability may exist", name)
		}
	}
}

// TestTheSetMatchesTheSharedFixture holds this package and
// shared/culprit_model/capabilities.py to one list. Before the Phase 30
// invariant audit the Python side accepted any string as a capability, so
// a capture listing `db.schema.write` was stored and served back as a
// grant it "ran under"; the fixture is what keeps the two sides saying the
// same thing from here on.
func TestTheSetMatchesTheSharedFixture(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "capability_conformance.json"))
	if err != nil {
		t.Fatalf("the shared fixture is missing: %v", err)
	}
	var fixture struct {
		Capabilities []struct {
			Name      string `json:"name"`
			Allowlist bool   `json:"allowlist"`
		} `json:"capabilities"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	if len(fixture.Capabilities) != len(known) {
		t.Errorf("the fixture names %d capabilities, this package %d",
			len(fixture.Capabilities), len(known))
	}
	for _, entry := range fixture.Capabilities {
		takesList, ok := known[Capability(entry.Name)]
		if !ok {
			t.Errorf("%s is in the shared fixture and unknown here", entry.Name)
			continue
		}
		if takesList != entry.Allowlist {
			t.Errorf("%s: allowlist is %t here and %t in the fixture", entry.Name, takesList, entry.Allowlist)
		}
	}
}
