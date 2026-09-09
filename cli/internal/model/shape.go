package model

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// ValueShape — what a config value *is*, with no way to say what it *says*.
//
// The Go mirror of shared/culprit_model/shape.py; read that file's
// header for the full reasoning. The short version: the artefact this
// guarantee is about is a capture bundle written to a file and attached
// to a bug report, so the guarantee has to live in the type rather than
// in a Postgres CHECK constraint the bundle never meets.
//
// Four fields, all closed. There is no field a string can be put in —
// not "no field one *should* put a string in", no field one *can*.
// Which means marshalling a ValueShape cannot leak a config value, and
// unmarshalling untrusted JSON into one cannot smuggle an extra key past
// it (UnmarshalJSON rejects unknown fields explicitly; encoding/json
// would otherwise ignore them silently, which is a different and worse
// failure than Python's).
type ValueShape struct {
	Type        ValueType   `json:"type"`
	LengthClass LengthClass `json:"length_class"`
	Format      ValueFormat `json:"format"`
	// Present reports whether the key was set at all. present=false is
	// the single most common real finding ("declared in .env.example,
	// unset in staging") and needs to be expressible without inventing a
	// fake value to describe.
	Present bool `json:"present"`
}

// ValueType is the JSON-ish type of a config value.
type ValueType string

const (
	TypeString  ValueType = "string"
	TypeInteger ValueType = "integer"
	TypeNumber  ValueType = "number"
	TypeBoolean ValueType = "boolean"
	TypeList    ValueType = "list"
	TypeMapping ValueType = "mapping"
	TypeNull    ValueType = "null"
	TypeUnknown ValueType = "unknown"
)

// LengthClass is a coarse bucket, never a length. A length is a small
// leak — it distinguishes a 32-character key from a 64-character one —
// and no comparison in this plan needs it.
type LengthClass string

const (
	LengthNotApplicable LengthClass = "not_applicable"
	LengthEmpty         LengthClass = "empty"
	LengthShort         LengthClass = "short"
	LengthMedium        LengthClass = "medium"
	LengthLong          LengthClass = "long"
)

// ValueFormat is the format class a value appears to be in — the only
// place any judgement about a value's content is recorded.
type ValueFormat string

const (
	FormatOpaque        ValueFormat = "opaque"
	FormatURL           ValueFormat = "url"
	FormatDSN           ValueFormat = "dsn"
	FormatEmail         ValueFormat = "email"
	FormatHostname      ValueFormat = "hostname"
	FormatIPAddress     ValueFormat = "ip_address"
	FormatPort          ValueFormat = "port"
	FormatPath          ValueFormat = "path"
	FormatDuration      ValueFormat = "duration"
	FormatBooleanish    ValueFormat = "booleanish"
	FormatNumeric       ValueFormat = "numeric"
	FormatUUID          ValueFormat = "uuid"
	FormatJSON          ValueFormat = "json"
	FormatSecret        ValueFormat = "secret"
	FormatList          ValueFormat = "list"
	FormatNotApplicable ValueFormat = "not_applicable"
)

// Ordered: first match wins, so more specific patterns come first. DSN
// before URL because every DSN is also a URL; SECRET before everything,
// because a JWT is also opaque-shaped and the more alarming answer is
// the one worth keeping. Mirrors shape.py's _FORMAT_PATTERNS exactly.
var formatPatterns = []struct {
	format  ValueFormat
	pattern *regexp.Regexp
}{
	{FormatSecret, regexp.MustCompile(
		`^-----BEGIN [A-Z ]*PRIVATE KEY-----` +
			`|^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.` +
			`|^AKIA[0-9A-Z]{16}$` +
			`|^gh[pousr]_[A-Za-z0-9]{20,}$` +
			`|^sk-[A-Za-z0-9]{20,}$` +
			`|^xox[baprs]-[A-Za-z0-9-]{10,}$`)},
	{FormatDSN, regexp.MustCompile(`(?i)^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]*@`)},
	{FormatURL, regexp.MustCompile(`(?i)^[a-z][a-z0-9+.-]*://`)},
	{FormatUUID, regexp.MustCompile(
		`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)},
	{FormatEmail, regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)},
	{FormatBooleanish, regexp.MustCompile(`(?i)^(true|false|yes|no|on|off|1|0)$`)},
	{FormatPort, regexp.MustCompile(`^(?:[1-9]\d{0,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2})$`)},
	{FormatDuration, regexp.MustCompile(`(?i)^\d+(?:\.\d+)?\s*(?:ms|s|m|h|d)$`)},
	{FormatNumeric, regexp.MustCompile(`^-?\d+(?:\.\d+)?$`)},
	{FormatIPAddress, regexp.MustCompile(
		`(?i)^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?$|^\[?[0-9a-f:]{3,}\]?(?::\d+)?$`)},
	{FormatPath, regexp.MustCompile(`^(?:/|\./|\.\./|[A-Za-z]:[\\/])`)},
	{FormatJSON, regexp.MustCompile(`^\s*[\[{]`)},
	{FormatHostname, regexp.MustCompile(
		`(?i)^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(?::\d{1,5})?$`)},
}

// Length bucket boundaries, in characters. Chosen so the buckets mean
// something to a reader rather than being evenly spaced.
const (
	shortMax  = 16
	mediumMax = 128
)

// AbsentShape is the shape of a config key that is not set.
func AbsentShape() ValueShape {
	return ValueShape{
		Type:        TypeNull,
		LengthClass: LengthNotApplicable,
		Format:      FormatNotApplicable,
		Present:     false,
	}
}

// UnknownShape is a key known to exist whose value the extractor could
// not read. Distinct from AbsentShape: "declared in .env.example, and I
// have no access to this environment's value" is not the same claim as
// "unset", and collapsing them would manufacture divergences.
func UnknownShape() ValueShape {
	return ValueShape{
		Type:        TypeUnknown,
		LengthClass: LengthNotApplicable,
		Format:      FormatNotApplicable,
		Present:     true,
	}
}

// ShapeOfString classifies a real string value, returning something that
// cannot leak it. Callers hold the value; what they hand on is this.
func ShapeOfString(value string) ValueShape {
	return ValueShape{
		Type:        TypeString,
		LengthClass: lengthClassOf(len(value)),
		Format:      ClassifyFormat(value),
		Present:     true,
	}
}

// ClassifyFormat returns the format class of a string. Pure, total, and
// it never echoes its input.
func ClassifyFormat(text string) ValueFormat {
	candidate := strings.TrimSpace(text)
	if candidate == "" {
		return FormatNotApplicable
	}
	// Hostname is checked with a length guard here rather than in the
	// pattern: Go's RE2 has no lookahead, so the Python side's
	// `(?=.{1,253}$)` has no direct translation. Same effect, stated
	// where it can be read.
	for _, entry := range formatPatterns {
		if entry.format == FormatHostname && len(candidate) > 253 {
			continue
		}
		if entry.pattern.MatchString(candidate) {
			return entry.format
		}
	}
	return FormatOpaque
}

func lengthClassOf(length int) LengthClass {
	switch {
	case length == 0:
		return LengthEmpty
	case length <= shortMax:
		return LengthShort
	case length <= mediumMax:
		return LengthMedium
	default:
		return LengthLong
	}
}

// shapeWire is ValueShape without the custom unmarshaller, so
// UnmarshalJSON can decode into it without recursing.
//
// Pointers, so a *missing* field is distinguishable from a zero one.
// Go has no "required field" for encoding/json: without this, a shape
// arriving without `present` decodes to `present: false` and one without
// `type` to `type: ""`, both silently. `present` is the field that says
// whether a key was actually set, so quietly inventing an answer for it
// is a fact invented rather than read. Python makes all four required
// for the same reason.
type shapeWire struct {
	Type        *ValueType   `json:"type"`
	LengthClass *LengthClass `json:"length_class"`
	Format      *ValueFormat `json:"format"`
	Present     *bool        `json:"present"`
}

// UnmarshalJSON rejects any field that is not one of the four.
//
// encoding/json ignores unknown fields by default, which would let
// {"type":"url","sample":"postgresql://u:hunter2@db/orders"} round-trip
// through a ValueShape losing only the part that matters — a silent
// success where Python raises. DisallowUnknownFields makes the Go side
// refuse it the same way.
func (s *ValueShape) UnmarshalJSON(data []byte) error {
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	var wire shapeWire
	if err := decoder.Decode(&wire); err != nil {
		return err
	}
	if wire.Type == nil || wire.LengthClass == nil || wire.Format == nil || wire.Present == nil {
		return fmt.Errorf(
			"a value_shape needs all four of type, length_class, format and present; " +
				"a missing one would be filled in with an answer the extractor never gave")
	}
	*s = ValueShape{
		Type:        *wire.Type,
		LengthClass: *wire.LengthClass,
		Format:      *wire.Format,
		Present:     *wire.Present,
	}
	return nil
}
