package capability

import (
	"fmt"
	"sync"
	"testing"
)

// TestTheLedgerIsSafeForConcurrentUse is the regression test for a crash
// found in Phase 31.1: `culprit probe` runs probes concurrently, each asks
// the ledger before dialling, and the ledger's maps were unguarded, so the
// probe suite died intermittently with "concurrent map writes". The Go
// runtime aborts on that reliably under this much contention, so this
// fails without the race detector (which needs cgo) as well as with it.
func TestTheLedgerIsSafeForConcurrentUse(t *testing.T) {
	enabled := true
	grants, err := Parse(map[string]Raw{
		"net.tcp.connect":        {Enabled: &enabled},
		"process.exec.allowlist": {Items: []string{"pip-freeze"}},
	})
	if err != nil {
		t.Fatalf("building grants: %v", err)
	}
	ledger := NewLedger(grants)

	var wait sync.WaitGroup
	for worker := 0; worker < 64; worker++ {
		wait.Add(1)
		go func(worker int) {
			defer wait.Done()
			for call := 0; call < 200; call++ {
				component := fmt.Sprintf("c%d", (worker+call)%17)
				ledger.Require(NetTCPConnect, component, "dial")
				ledger.Require(DBMetadataRead, component, "schema")
				ledger.RequireItem(ProcessExecAllowlist, "other", component, "packages")
				ledger.Refuse(NetHTTPOutbound, component, "http", "not granted")
				_ = ledger.Refusals()
				_ = ledger.Records()
			}
		}(worker)
	}
	wait.Wait()

	// 17 components x 3 refused checks, each recorded exactly once.
	if got := len(ledger.Refusals()); got != 17*3 {
		t.Errorf("recorded %d refusals, want %d — deduplication lost under contention", got, 17*3)
	}
}
