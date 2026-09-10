// Package capability is Phase 30's permission model (§2.7): grant
// parsing, enforcement, and the `refused` path.
//
// # The shape of the thing
//
// A capability is a coarse, named, human-legible permission — the
// sentence a person reads before deciding to give a tool access to their
// production environment. Grants are written in `culprit.yaml`, per
// environment, by the user, and reviewed like any other committed file:
//
//	environments:
//	  production:
//	    grants:
//	      config.read.names: true
//	      config.read.values: [orders-api/LOG_LEVEL]
//	      db.metadata.read: true
//
// Every piece of capture code asks a Ledger before it looks at anything.
// If the capability was not granted, the Ledger records a **refusal** and
// the check does not happen. It is never a silent omission: "I could not
// check X because you have not granted Y" is a line in the report, and
// the alternative — a fact that simply is not there — reads as "nothing
// wrong with X", which is the single most damaging thing this tool could
// say.
//
// # What does not exist
//
// **No `*.write` capability exists** (§2.7, and docs/HANDOFF.md §2:
// "structural boundary, not a config flag"). Naming one in a manifest is
// a validation error, not an ignored key — a user who wrote
// `db.schema.write: true` believes they granted something, and a tool
// that quietly ignored it would leave them believing it.
//
// Deterministic and dependency-free: this package knows nothing about
// Docker, SQL or DNS, only names.
package capability

import (
	"fmt"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Capability is one §2.7 name.
type Capability string

// The closed set, verbatim from docs/DIAGNOSTIC_PLAN.md §2.7.
//
// Several are declared here and exercised by nothing in Phase 30 —
// telemetry reads are Phase 31's probes, `db.rows.read` has no reader at
// all. They are accepted so that a manifest written against §2.7 loads,
// and recorded as granted-and-unused so the capture says so. An unknown
// name is refused; see Parse.
const (
	ModelRead            Capability = "model.read"
	RepoRead             Capability = "repo.read"
	ConfigReadNames      Capability = "config.read.names"
	ConfigReadValues     Capability = "config.read.values"
	DBMetadataRead       Capability = "db.metadata.read"
	DBRowsRead           Capability = "db.rows.read"
	NetDNSResolve        Capability = "net.dns.resolve"
	NetTCPConnect        Capability = "net.tcp.connect"
	NetTLSInspect        Capability = "net.tls.inspect"
	NetHTTPOutbound      Capability = "net.http.outbound"
	TelemetryLogsRead    Capability = "telemetry.logs.read"
	TelemetryMetricsRead Capability = "telemetry.metrics.read"
	TelemetryTracesRead  Capability = "telemetry.traces.read"
	DeployMetadataRead   Capability = "deploy.metadata.read"
	ProcessExecAllowlist Capability = "process.exec.allowlist"
)

// known is every capability, and whether it takes an allowlist.
//
// The three that take one are the three §2.7 marks "opt-in, per-key" or
// "named commands only": reading a config *value*, reading database
// *rows*, and executing a command. For those, `true` is refused. A
// blanket grant is precisely the thing the per-item rule exists to
// prevent, and accepting `config.read.values: true` as "every key" would
// turn the most sensitive capability in the list into the easiest one to
// grant.
var known = map[Capability]bool{
	ModelRead:            false,
	RepoRead:             false,
	ConfigReadNames:      false,
	ConfigReadValues:     true,
	DBMetadataRead:       false,
	DBRowsRead:           true,
	NetDNSResolve:        false,
	NetTCPConnect:        false,
	NetTLSInspect:        false,
	NetHTTPOutbound:      false,
	TelemetryLogsRead:    false,
	TelemetryMetricsRead: false,
	TelemetryTracesRead:  false,
	DeployMetadataRead:   false,
	ProcessExecAllowlist: true,
}

// TakesAllowlist reports whether a capability is granted per item.
func TakesAllowlist(capability Capability) bool { return known[capability] }

// Known reports whether a name is a §2.7 capability.
func Known(name string) bool {
	_, ok := known[Capability(name)]
	return ok
}

// Grants is one environment's grant set.
type Grants struct {
	granted map[Capability]bool
	allow   map[Capability]map[string]bool
}

// Raw is one grant as written: either a bool or a list of items. The
// manifest loader decodes YAML into this so this package need not know
// about YAML.
type Raw struct {
	Enabled *bool
	Items   []string
}

// Parse validates and builds a grant set.
//
// Refusals here are loud and name the problem precisely, because a
// grant that does not parse is a permission the user believes they
// either gave or withheld — and either way they are wrong about what the
// tool can see.
func Parse(raw map[string]Raw) (Grants, error) {
	grants := Grants{granted: map[Capability]bool{}, allow: map[Capability]map[string]bool{}}

	names := make([]string, 0, len(raw))
	for name := range raw {
		names = append(names, name)
	}
	sort.Strings(names)

	for _, name := range names {
		entry := raw[name]
		capability := Capability(name)
		if strings.HasSuffix(name, ".write") {
			return Grants{}, fmt.Errorf(
				"grants.%s: no write capability exists (docs/DIAGNOSTIC_PLAN.md §2.7). "+
					"Culprit reads environments; it never changes them, and there is no "+
					"setting that makes it", name)
		}
		takesList, ok := known[capability]
		if !ok {
			return Grants{}, fmt.Errorf(
				"grants.%s: not a capability. See docs/PERMISSIONS.md for the list "+
					"(a typo here is a permission you believe you gave and did not)", name)
		}
		switch {
		case takesList && entry.Enabled != nil:
			return Grants{}, fmt.Errorf(
				"grants.%s: needs an explicit list, not true/false. It is granted per "+
					"item so that nothing is ever granted by accident — name each one", name)
		case takesList:
			if len(entry.Items) == 0 {
				// An empty list grants nothing. Refused rather than accepted
				// as a no-op, because `config.read.values: []` reads as a
				// grant and is not one.
				return Grants{}, fmt.Errorf(
					"grants.%s: an empty list grants nothing; remove the line instead", name)
			}
			set := map[string]bool{}
			for _, item := range entry.Items {
				item = strings.TrimSpace(item)
				if item == "" || item == "*" || strings.Contains(item, "*") {
					return Grants{}, fmt.Errorf(
						"grants.%s: items must be named exactly; wildcards are not supported", name)
				}
				set[item] = true
			}
			grants.granted[capability] = true
			grants.allow[capability] = set
		default:
			if entry.Enabled == nil {
				return Grants{}, fmt.Errorf("grants.%s: expected true or false", name)
			}
			if *entry.Enabled {
				grants.granted[capability] = true
			}
		}
	}
	return grants, nil
}

// Has reports whether a capability was granted at all.
func (g Grants) Has(capability Capability) bool { return g.granted[capability] }

// Allows reports whether one item is on a capability's allowlist.
func (g Grants) Allows(capability Capability, item string) bool {
	return g.granted[capability] && g.allow[capability][item]
}

// Ledger records what one capture was allowed to do, what it did, and
// what it was refused.
//
// One per capture. The capture code never checks Grants directly: it
// asks the Ledger, so that a check which is not allowed *always* leaves
// a refusal behind. A code path that consulted Grants.Has and then
// forgot to record anything is the silent omission this package exists
// to make impossible.
type Ledger struct {
	grants  Grants
	used    map[Capability]bool
	refused []model.Refusal
	seen    map[string]bool
}

// NewLedger starts a ledger over a grant set.
func NewLedger(grants Grants) *Ledger {
	return &Ledger{grants: grants, used: map[Capability]bool{}, seen: map[string]bool{}}
}

// Require asks for a capability before doing `check` on `component`. It
// returns true if the check may proceed; otherwise it records why not.
func (l *Ledger) Require(capability Capability, component, check string) bool {
	if l.grants.Has(capability) {
		l.used[capability] = true
		return true
	}
	l.refuse(capability, component, check, fmt.Sprintf("%s is not granted", capability))
	return false
}

// RequireItem asks for one item of an allowlisted capability.
//
// A refusal for an unlisted item is recorded only when the capability is
// granted for *some* items — that is the case a reader needs to see ("you
// granted values for two keys; this one was not among them"). When the
// capability is not granted at all, the caller records one refusal for
// the whole check rather than one per key, via Require or Refuse, so a
// capture with forty keys does not produce forty identical lines.
func (l *Ledger) RequireItem(capability Capability, item, component, check string) bool {
	if l.grants.Allows(capability, item) {
		l.used[capability] = true
		return true
	}
	if l.grants.Has(capability) {
		l.refuse(capability, component, check,
			fmt.Sprintf("%s is granted, but not for %s", capability, item))
	}
	return false
}

// Refuse records a refusal the caller has already decided on. Used when
// a check needs two capabilities and the reason should name both.
func (l *Ledger) Refuse(capability Capability, component, check, reason string) {
	l.refuse(capability, component, check, reason)
}

func (l *Ledger) refuse(capability Capability, component, check, reason string) {
	key := string(capability) + "\x00" + component + "\x00" + check
	if l.seen[key] {
		return
	}
	l.seen[key] = true
	l.refused = append(l.refused, model.Refusal{
		Capability: string(capability),
		Component:  component,
		Check:      check,
		Reason:     reason,
	})
}

// Refusals returns every refusal, in a stable order.
func (l *Ledger) Refusals() []model.Refusal {
	refused := append([]model.Refusal(nil), l.refused...)
	sort.SliceStable(refused, func(i, j int) bool {
		if refused[i].Component != refused[j].Component {
			return refused[i].Component < refused[j].Component
		}
		if refused[i].Check != refused[j].Check {
			return refused[i].Check < refused[j].Check
		}
		return refused[i].Capability < refused[j].Capability
	})
	return refused
}

// Records returns the grant set as the capture bundle carries it:
// every granted capability, its allowlist, and whether it was used.
func (l *Ledger) Records() []model.Grant {
	records := make([]model.Grant, 0, len(l.grants.granted))
	for capability := range l.grants.granted {
		record := model.Grant{Capability: string(capability), Used: l.used[capability]}
		for item := range l.grants.allow[capability] {
			record.Allow = append(record.Allow, item)
		}
		sort.Strings(record.Allow)
		records = append(records, record)
	}
	sort.Slice(records, func(i, j int) bool { return records[i].Capability < records[j].Capability })
	return records
}
