package extract

import (
	"fmt"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The parts of culprit.yaml that `culprit check` reads and `culprit
// intent` does not: connections (which give severity its graph),
// invariants, suppressions and severity overrides (Phase 29 field 10).
//
// They live here rather than in manifest.go to keep the split visible:
// manifest.go is what extraction needs, this is what comparison needs,
// and a reader of either can see which half they are in.

// ManifestConnection is one outgoing edge, nested under its source
// component exactly as `api/app/model/manifest.py` nests it.
//
// Nested, not a flat list, and the reason is the same one the Python
// loader gives: a connection has no identity apart from the pair it
// joins, and a flat form makes it possible to declare an edge whose
// source is not in the file — a hole in the model that reads as an edge.
type ManifestConnection struct {
	To   string `yaml:"to"`
	Kind string `yaml:"kind"`
	// Criticality is `on_request_path`, `background` or `unknown`.
	// It is the single most load-bearing field in severity: an edge on
	// the request path is what turns a divergence into
	// `breaks_request_path`.
	Criticality string `yaml:"criticality"`
}

// Invariant is a developer assertion — confidence rank 100, the top of
// §2.4, above anything extracted.
//
// This is the one place a human states intent directly rather than
// having it read out of code, and it exists because some intent lives
// nowhere else: "this route must keep returning 200" is not derivable
// from a route table. An invariant becomes an ordinary INTENT fact, so
// it is compared by the same generic comparator as everything else (D7)
// rather than by a special case.
type Invariant struct {
	// Subject is a subject URI, written by hand. It is validated by
	// being parsed and rebuilt — a typo'd subject would otherwise sit in
	// the file asserting something about nothing, forever, and never
	// compare against anything.
	Subject   string `yaml:"subject"`
	Predicate string `yaml:"predicate"`
	// Value is compared with `values_equal` semantics. Absent means the
	// assertion is bare existence: "this subject must exist", which is
	// the common case.
	Value any `yaml:"value"`
	// Why is required. An invariant nobody explained is one nobody can
	// safely delete, and this file outlives the person who wrote it.
	Why string `yaml:"why"`
}

// Suppression silences a finding, with a reason and optionally an expiry.
//
// **The reason is required** (field 8). A suppression with no reason is
// indistinguishable from a bug someone hid, and the whole value of this
// tool is that its findings are trustworthy — a suppression list nobody
// can audit is how that trust is lost. `expires` is optional and is a
// deliberate second chance: it turns "we will fix this later" into
// something that says so out loud on a date.
type Suppression struct {
	Subject   string `yaml:"subject"`
	Predicate string `yaml:"predicate"`
	Reason    string `yaml:"reason"`
	// Expires is YYYY-MM-DD. After it, the suppression stops applying
	// and the finding comes back — it does not silently keep working.
	Expires string `yaml:"expires"`
}

// SeverityOverride reclassifies findings on matching subjects.
//
// Severity is computed from the system model (§2.5) and the model does
// not know everything: a config key the graph thinks is cosmetic may be
// the one that takes payments down. This is the escape hatch, and like a
// suppression it requires a reason.
type SeverityOverride struct {
	Subject  string `yaml:"subject"`
	Severity string `yaml:"severity"`
	Reason   string `yaml:"reason"`
}

// PolicyError is a `culprit.yaml` whose check-time sections cannot be
// used. Loud, and refused at load: a suppression that does not parse is
// a finding silently not silenced, or worse, silently silenced.
type PolicyError struct{ Message string }

func (e *PolicyError) Error() string { return e.Message }

// validatePolicy checks the sections `culprit check` reads.
//
// Every rule here refuses rather than warns. A warning in a CI tool is
// read once and then never again, and each of these mistakes is the kind
// that makes the tool quietly report the wrong thing rather than fail.
func (m *Manifest) validatePolicy() error {
	known := map[string]bool{}
	for _, component := range m.Components {
		known[component.Name] = true
	}

	for _, component := range m.Components {
		for _, connection := range component.Connections {
			if connection.To == "" {
				return &PolicyError{Message: fmt.Sprintf(
					"components.%s.connections: an edge has no `to`", component.Name)}
			}
			if !known[connection.To] {
				return &PolicyError{Message: fmt.Sprintf(
					"components.%s.connections: `to: %s` is not a component in this file. "+
						"Declare it, even as a bare `- name: %s` — an edge to something "+
						"undeclared is a hole in the model that reads as an edge.",
					component.Name, connection.To, connection.To)}
			}
			if connection.Criticality != "" && !validCriticality[connection.Criticality] {
				return &PolicyError{Message: fmt.Sprintf(
					"components.%s.connections.%s: criticality %q is not one of %s",
					component.Name, connection.To, connection.Criticality,
					strings.Join(sortedKeysOf(validCriticality), ", "))}
			}
		}
	}

	for index, invariant := range m.Invariants {
		where := fmt.Sprintf("invariants[%d]", index)
		if strings.TrimSpace(invariant.Why) == "" {
			return &PolicyError{Message: where +
				": `why` is required. An invariant nobody explained is one nobody can " +
				"safely delete, and this file outlives whoever wrote it."}
		}
		if strings.TrimSpace(invariant.Predicate) == "" {
			return &PolicyError{Message: where + ": `predicate` is required"}
		}
		if err := checkSubject(where, invariant.Subject); err != nil {
			return err
		}
	}

	for index, suppression := range m.Suppress {
		where := fmt.Sprintf("suppress[%d]", index)
		if strings.TrimSpace(suppression.Reason) == "" {
			// Field 8, verbatim: a suppression with no reason fails
			// validation. It is the difference between "we decided this
			// is fine" and "somebody made a finding go away".
			return &PolicyError{Message: where +
				": `reason` is required. A suppression with no reason is " +
				"indistinguishable from a bug somebody hid."}
		}
		if err := checkSubject(where, suppression.Subject); err != nil {
			return err
		}
		if suppression.Expires != "" {
			if _, err := time.Parse("2006-01-02", suppression.Expires); err != nil {
				return &PolicyError{Message: fmt.Sprintf(
					"%s: `expires: %s` is not a YYYY-MM-DD date", where, suppression.Expires)}
			}
		}
	}

	for index, override := range m.SeverityOverrides {
		where := fmt.Sprintf("severity_overrides[%d]", index)
		if strings.TrimSpace(override.Reason) == "" {
			return &PolicyError{Message: where + ": `reason` is required"}
		}
		if !validSeverity[override.Severity] {
			return &PolicyError{Message: fmt.Sprintf(
				"%s: severity %q is not one of %s", where, override.Severity,
				strings.Join(sortedKeysOf(validSeverity), ", "))}
		}
		if err := checkSubject(where, override.Subject); err != nil {
			return err
		}
	}
	return nil
}

// checkSubject accepts a canonical subject URI, or a prefix pattern
// ending in `*`.
//
// A pattern is allowed for suppressions and overrides because silencing
// one route at a time is unusable, and refused for invariants because an
// assertion about "everything matching this" is not an assertion about
// anything in particular.
func checkSubject(where, subject string) error {
	if strings.TrimSpace(subject) == "" {
		return &PolicyError{Message: where + ": `subject` is required"}
	}
	if strings.HasSuffix(subject, "*") {
		// A bare `*`, or a pattern with nothing before the star, would
		// match every subject there is: one line with one reason turning
		// the whole tool off. That is not a suppression, it is an
		// uninstall with a comment attached, and it would be invisible in
		// a report that dutifully said "0 divergences".
		//
		// A prefix has to be specific enough to name what it is
		// silencing. `http:orders-api/*` is a decision about a component;
		// `*` is not a decision about anything.
		prefix := strings.TrimSuffix(subject, "*")
		if !strings.Contains(prefix, ":") {
			return &PolicyError{Message: fmt.Sprintf(
				"%s: %q matches every subject in the system. A pattern must name "+
					"at least a subject kind and component, like "+
					"\"http:orders-api/*\" — silencing everything is not a "+
					"decision anybody can review.", where, subject)}
		}
		return nil
	}
	kind, parts, err := model.ParseSubject(subject)
	if err != nil {
		return &PolicyError{Message: fmt.Sprintf(
			"%s: %q is not a subject URI (%s). A subject that does not parse asserts "+
				"something about nothing and would never match a fact.", where, subject, err)}
	}
	rebuilt, err := model.BuildSubject(kind, parts)
	if err != nil || rebuilt != subject {
		return &PolicyError{Message: fmt.Sprintf(
			"%s: %q is not in canonical form (it should be %q). Comparison is subject "+
				"equality, so a non-canonical subject silently matches nothing.",
			where, subject, rebuilt)}
	}
	return nil
}

var validCriticality = map[string]bool{
	"on_request_path": true,
	"background":      true,
	"unknown":         true,
}

var validSeverity = map[string]bool{
	string(model.SeverityBreaksRequestPath): true,
	string(model.SeverityDegrades):          true,
	string(model.SeverityCosmetic):          true,
	string(model.SeverityUnknown):           true,
}

func sortedKeysOf(values map[string]bool) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sortStrings(keys)
	return keys
}

// Active reports whether a suppression still applies on the given day.
//
// An expired suppression does not silently keep working — that is the
// whole point of the field. `now` is passed in rather than read from the
// clock so the behaviour is testable on both sides of the date.
func (s Suppression) Active(now time.Time) bool {
	if s.Expires == "" {
		return true
	}
	expiry, err := time.Parse("2006-01-02", s.Expires)
	if err != nil {
		// Unparseable dates are refused at load; reaching here means a
		// Suppression was built in code. Treating it as expired is the
		// safe direction: a finding shown is recoverable, a finding
		// hidden is not.
		return false
	}
	// Inclusive: a suppression expiring today is still good today.
	return !now.Truncate(24 * time.Hour).After(expiry)
}

// Matches reports whether this suppression covers a finding.
//
// An empty predicate matches any predicate on the subject; a subject
// ending in `*` matches by prefix. Both narrow-by-default: an empty
// subject matches nothing, so a malformed entry silences nothing rather
// than everything.
func (s Suppression) Matches(subject, predicate string) bool {
	if s.Predicate != "" && s.Predicate != predicate {
		return false
	}
	return subjectMatches(s.Subject, subject)
}

// Matches reports whether this override applies to a subject.
func (o SeverityOverride) Matches(subject string) bool {
	return subjectMatches(o.Subject, subject)
}

func subjectMatches(pattern, subject string) bool {
	if pattern == "" {
		return false
	}
	if strings.HasSuffix(pattern, "*") {
		return strings.HasPrefix(subject, strings.TrimSuffix(pattern, "*"))
	}
	return pattern == subject
}

// ApplySuppressions marks matching findings suppressed, in place.
//
// **Marked, not removed.** A suppressed finding keeps its severity and
// carries the reason someone gave for silencing it, so `--format json`
// and the text report can both say "and 4 more, suppressed because X".
// Deleting them here would make the suppression list unauditable from
// the tool's own output, which is the failure mode `reason` is required
// to prevent — a list nobody can review is a list that accumulates.
//
// Returns the number suppressed. `now` is passed in rather than read
// from the clock so an expiry is testable on both sides of its date.
func (m *Manifest) ApplySuppressions(divergences []model.Divergence, now time.Time) int {
	if m == nil {
		return 0
	}
	count := 0
	for index := range divergences {
		for _, suppression := range m.Suppress {
			if !suppression.Active(now) {
				continue
			}
			if !suppression.Matches(divergences[index].Subject, divergences[index].Predicate) {
				continue
			}
			divergences[index].Status = model.StatusSuppressed
			divergences[index].SuppressedBy = suppression.Reason
			count++
			break
		}
	}
	return count
}

// ExpiredSuppressions lists suppressions whose date has passed.
//
// Surfaced by `culprit check` as a note rather than a finding. An expiry
// that quietly stops applying leaves a line in `culprit.yaml` that looks
// like it is doing something and is not, and the next person to read the
// file will believe it. Saying so out loud is the entire reason the
// field exists.
func (m *Manifest) ExpiredSuppressions(now time.Time) []Suppression {
	if m == nil {
		return nil
	}
	var expired []Suppression
	for _, suppression := range m.Suppress {
		if suppression.Expires != "" && !suppression.Active(now) {
			expired = append(expired, suppression)
		}
	}
	return expired
}
