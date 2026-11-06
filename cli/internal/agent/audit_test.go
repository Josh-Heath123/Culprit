package agent

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func writeEntries(t *testing.T, count int) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "audit.log")
	log, err := OpenAudit(path)
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < count; index++ {
		if _, err := log.Append(Entry{
			Time: time.Date(2026, 11, 5, 12, 0, index, 0, time.UTC), AgentID: "a1",
			TaskID: "t1", Kind: EntryProbe, ProbeID: "probe.net.tcp_connect",
			Target: "component:orders", Grants: []string{"net.tcp.connect"}, Verdict: "pass",
		}); err != nil {
			t.Fatal(err)
		}
	}
	return path
}

func lines(t *testing.T, path string) []string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimRight(string(data), "\n"), "\n")
}

func rewrite(t *testing.T, path string, kept []string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(strings.Join(kept, "\n")+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestAnIntactChainVerifies(t *testing.T) {
	path := writeEntries(t, 4)
	count, err := VerifyAudit(path)
	if err != nil || count != 4 {
		t.Fatalf("count %d, err %v", count, err)
	}
	// Reopening continues the chain rather than restarting it.
	log, err := OpenAudit(path)
	if err != nil {
		t.Fatal(err)
	}
	entry, err := log.Append(Entry{AgentID: "a1", TaskID: "t2", Kind: EntryTask, Outcome: OutcomeCompleted})
	if err != nil || entry.Seq != 5 {
		t.Fatalf("seq %d, err %v", entry.Seq, err)
	}
	if count, err := VerifyAudit(path); err != nil || count != 5 {
		t.Fatalf("after reopening: count %d, err %v", count, err)
	}
}

func TestAnEditedEntryIsCaught(t *testing.T) {
	path := writeEntries(t, 4)
	all := lines(t, path)
	all[1] = strings.Replace(all[1], `"verdict":"pass"`, `"verdict":"fail"`, 1)
	rewrite(t, path, all)
	_, err := VerifyAudit(path)
	if err == nil || !strings.Contains(err.Error(), "line 2") || !strings.Contains(err.Error(), "edited") {
		t.Fatalf("err = %v, want line 2 named as edited", err)
	}
}

func TestADeletedEntryIsCaught(t *testing.T) {
	path := writeEntries(t, 4)
	all := lines(t, path)
	rewrite(t, path, append(all[:1:1], all[2:]...))
	_, err := VerifyAudit(path)
	if err == nil || !strings.Contains(err.Error(), "line 2") {
		t.Fatalf("err = %v, want line 2 named", err)
	}
}

func TestADeletedEntryWithItsSuccessorRenumberedIsStillCaught(t *testing.T) {
	// Someone who knows the format removes entry 2 and renumbers entry 3:
	// its prev still names the removed entry's hash, and its own hash no
	// longer matches what it says.
	path := writeEntries(t, 3)
	all := lines(t, path)
	all[2] = strings.Replace(all[2], `"seq":3`, `"seq":2`, 1)
	rewrite(t, path, []string{all[0], all[2]})
	if _, err := VerifyAudit(path); err == nil || !strings.Contains(err.Error(), "line 2") {
		t.Fatalf("err = %v, want line 2 named", err)
	}
}

func TestReorderedEntriesAreCaught(t *testing.T) {
	path := writeEntries(t, 3)
	all := lines(t, path)
	rewrite(t, path, []string{all[0], all[2], all[1]})
	if _, err := VerifyAudit(path); err == nil {
		t.Fatal("a reordered log verified")
	}
}

func TestAnAgentWillNotAppendToABrokenChain(t *testing.T) {
	path := writeEntries(t, 3)
	all := lines(t, path)
	all[0] = strings.Replace(all[0], `"agent_id":"a1"`, `"agent_id":"a2"`, 1)
	rewrite(t, path, all)
	if _, err := OpenAudit(path); err == nil || !strings.Contains(err.Error(), "will not add to it") {
		t.Fatalf("err = %v, want a refusal to append", err)
	}
}

func TestAProbeEntryWithNoGrantsSaysSoExplicitly(t *testing.T) {
	path := filepath.Join(t.TempDir(), "audit.log")
	log, _ := OpenAudit(path)
	if _, err := log.Append(Entry{AgentID: "a1", TaskID: "t1", Kind: EntryProbe, Verdict: "refused"}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(lines(t, path)[0], `"grants":[]`) {
		t.Errorf("a refused probe's entry omits its (empty) grants: %s", lines(t, path)[0])
	}
}
