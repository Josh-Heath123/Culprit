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
// Five fields, all closed. There is no field a string can be put in —
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
	// Scheme is the fifth field, added in Phase 30 (resolving Q7,
	// docs/HANDOFF.md §2): "the application declares a `postgresql` URL
	// and the environment holds a `mysql` one" is a real fault class,
	// and without this field the two have identical shapes.
	//
	// A closed enum, never the scheme string itself — UnmarshalJSON
	// refuses anything outside the set, so `scheme` cannot become the
	// field a DSN is smuggled through.
	//
	// **Optional on the wire, and absent means "not classified".** The
	// other four are required because a missing one would be filled in
	// with an answer the extractor never gave. A missing scheme is
	// different in kind: protocol-1 extractors written before the field
	// existed say nothing about schemes, and "said nothing" is exactly
	// what the empty value records. Equivalent treats it that way, so an
	// older extractor's shape never disagrees with a newer one's merely
	// by being older.
	Scheme ValueScheme `json:"scheme,omitempty"`
}

// ValueScheme is the scheme of a URL- or DSN-shaped value, from a closed
// set. `other` is the honest answer for a scheme outside it; the scheme
// itself is never recorded.
type ValueScheme string

const (
	SchemeNotApplicable ValueScheme = "not_applicable"
	SchemePostgreSQL    ValueScheme = "postgresql"
	SchemeMySQL         ValueScheme = "mysql"
	SchemeMariaDB       ValueScheme = "mariadb"
	SchemeSQLite        ValueScheme = "sqlite"
	SchemeMSSQL         ValueScheme = "mssql"
	SchemeOracle        ValueScheme = "oracle"
	SchemeMongoDB       ValueScheme = "mongodb"
	SchemeRedis         ValueScheme = "redis"
	SchemeRedisTLS      ValueScheme = "rediss"
	SchemeMemcached     ValueScheme = "memcached"
	SchemeAMQP          ValueScheme = "amqp"
	SchemeAMQPS         ValueScheme = "amqps"
	SchemeKafka         ValueScheme = "kafka"
	SchemeNATS          ValueScheme = "nats"
	SchemeHTTP          ValueScheme = "http"
	SchemeHTTPS         ValueScheme = "https"
	SchemeWS            ValueScheme = "ws"
	SchemeWSS           ValueScheme = "wss"
	SchemeGRPC          ValueScheme = "grpc"
	SchemeFTP           ValueScheme = "ftp"
	SchemeSFTP          ValueScheme = "sftp"
	SchemeS3            ValueScheme = "s3"
	SchemeGCS           ValueScheme = "gs"
	SchemeFile          ValueScheme = "file"
	SchemeLDAP          ValueScheme = "ldap"
	SchemeLDAPS         ValueScheme = "ldaps"
	SchemeSMTP          ValueScheme = "smtp"
	SchemeSMTPS         ValueScheme = "smtps"
	SchemeOther         ValueScheme = "other"
)

// knownSchemes is the closed set, and the one place the aliases a real
// scheme travels under are folded onto it. `postgres://` and
// `postgresql+asyncpg://` are one scheme with two spellings; treating
// them as different would report every SQLAlchemy URL as pointing at a
// different database from the libpq one describing the same server.
//
// `rediss` is deliberately *not* folded onto `redis`, nor `https` onto
// `http`: TLS-or-not is a genuine difference between two environments,
// and one worth seeing.
var knownSchemes = map[string]ValueScheme{
	"postgresql": SchemePostgreSQL,
	"postgres":   SchemePostgreSQL,
	"mysql":      SchemeMySQL,
	"mariadb":    SchemeMariaDB,
	"sqlite":     SchemeSQLite,
	"sqlite3":    SchemeSQLite,
	"mssql":      SchemeMSSQL,
	"sqlserver":  SchemeMSSQL,
	"oracle":     SchemeOracle,
	"mongodb":    SchemeMongoDB,
	"redis":      SchemeRedis,
	"rediss":     SchemeRedisTLS,
	"memcached":  SchemeMemcached,
	"amqp":       SchemeAMQP,
	"amqps":      SchemeAMQPS,
	"kafka":      SchemeKafka,
	"nats":       SchemeNATS,
	"http":       SchemeHTTP,
	"https":      SchemeHTTPS,
	"ws":         SchemeWS,
	"wss":        SchemeWSS,
	"grpc":       SchemeGRPC,
	"ftp":        SchemeFTP,
	"sftp":       SchemeSFTP,
	"s3":         SchemeS3,
	"gs":         SchemeGCS,
	"file":       SchemeFile,
	"ldap":       SchemeLDAP,
	"ldaps":      SchemeLDAPS,
	"smtp":       SchemeSMTP,
	"smtps":      SchemeSMTPS,
}

// schemePattern reads the scheme off the front of a value. Only the
// scheme: nothing after `://` is looked at, so nothing after it can
// influence the answer or be retained by it.
var schemePattern = regexp.MustCompile(`^([A-Za-z][A-Za-z0-9+.-]*)://`)

// ClassifyScheme returns the scheme class of a string. Pure, total, and
// it never echoes its input: an unrecognised scheme is `other`, not the
// scheme, because a free string is the one thing this type may not hold.
//
// A driver suffix is dropped before lookup — `postgresql+asyncpg` is
// SQLAlchemy telling itself which driver to load, not a different kind
// of database — and `mongodb+srv` is `mongodb` for the same reason.
func ClassifyScheme(text string) ValueScheme {
	match := schemePattern.FindStringSubmatch(strings.TrimSpace(text))
	if match == nil {
		return SchemeNotApplicable
	}
	scheme := strings.ToLower(match[1])
	if base, _, found := strings.Cut(scheme, "+"); found {
		scheme = base
	}
	if known, ok := knownSchemes[scheme]; ok {
		return known
	}
	return SchemeOther
}

// Equivalent reports whether two shapes describe the same *kind* of
// value, which is the question every comparison of shapes is actually
// asking. It is not struct equality, in three deliberate ways:
//
//   - **Length class is compared only as empty-or-not.** Two
//     environments' database URLs are different lengths because they
//     name different hosts, and "short against medium" is not a claim
//     that either is wrong. An *empty* value where another environment
//     has one is — a present-but-blank key is a real misconfiguration
//     and one of the commonest — so that distinction survives.
//   - **An `unknown` type compares on presence alone.** shape.py says it
//     outright: "a comparison against UNKNOWN is not a divergence". A
//     key the capture knows is set but could not read (a Kubernetes
//     secret reference, say) disagrees with nothing about its content,
//     only, possibly, about whether it is there at all.
//   - **An unclassified scheme compares with anything.** See Scheme.
//
// Everything else — presence, type, format, a classified scheme — must
// match. Kept identical to `ValueShape.equivalent` in
// shared/culprit_model/shape.py by shared/tests/shape_equivalence_conformance.json,
// which both languages read.
func (s ValueShape) Equivalent(other ValueShape) bool {
	if s.Present != other.Present {
		return false
	}
	if !s.Present {
		return true
	}
	if s.Type == TypeUnknown || other.Type == TypeUnknown {
		return true
	}
	if s.Type != other.Type || s.Format != other.Format {
		return false
	}
	if s.Scheme != "" && other.Scheme != "" && s.Scheme != other.Scheme {
		return false
	}
	return (s.LengthClass == LengthEmpty) == (other.LengthClass == LengthEmpty)
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
		Scheme:      SchemeNotApplicable,
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
		Scheme:      SchemeNotApplicable,
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
		Scheme:      ClassifyScheme(value),
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
	Scheme      *ValueScheme `json:"scheme"`
}

// The closed sets, as sets. UnmarshalJSON checks membership against
// these; see its comment for why that check was missing and mattered.
var (
	knownTypes = map[ValueType]bool{
		TypeString: true, TypeInteger: true, TypeNumber: true, TypeBoolean: true,
		TypeList: true, TypeMapping: true, TypeNull: true, TypeUnknown: true,
	}
	knownLengthClasses = map[LengthClass]bool{
		LengthNotApplicable: true, LengthEmpty: true, LengthShort: true,
		LengthMedium: true, LengthLong: true,
	}
	knownFormats = map[ValueFormat]bool{
		FormatOpaque: true, FormatURL: true, FormatDSN: true, FormatEmail: true,
		FormatHostname: true, FormatIPAddress: true, FormatPort: true, FormatPath: true,
		FormatDuration: true, FormatBooleanish: true, FormatNumeric: true, FormatUUID: true,
		FormatJSON: true, FormatSecret: true, FormatList: true, FormatNotApplicable: true,
	}
	knownSchemeValues = func() map[ValueScheme]bool {
		set := map[ValueScheme]bool{SchemeNotApplicable: true, SchemeOther: true}
		for _, scheme := range knownSchemes {
			set[scheme] = true
		}
		return set
	}()
)

// UnmarshalJSON rejects any field that is not one of the five, and any
// value that is not in its field's closed set.
//
// encoding/json ignores unknown fields by default, which would let
// {"type":"url","sample":"postgresql://u:hunter2@db/orders"} round-trip
// through a ValueShape losing only the part that matters — a silent
// success where Python raises. DisallowUnknownFields makes the Go side
// refuse it the same way.
//
// # The membership check was missing until Phase 30
//
// Every field here is a named string type, and a named string type is
// still a string: `{"type":"postgresql://u:hunter2@db/orders", ...}`
// decoded without complaint, and `report.renderValue` prints
// `type/format/length_class` straight into SARIF. The header's claim that
// there is "no field a string can be put in" was true of the Python
// model, whose fields are enums, and false of this one. Found while
// adding `scheme` — the one field whose values actually look like the
// strings a secret starts with — and asking what would stop a
// third-party extractor from putting a DSN in it. The answer was
// nothing, for all five.
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
	// The error names the *field*, never the value — the value is
	// exactly what might be a credential.
	switch {
	case !knownTypes[*wire.Type]:
		return fmt.Errorf("value_shape.type is not one of the closed set of types")
	case !knownLengthClasses[*wire.LengthClass]:
		return fmt.Errorf("value_shape.length_class is not one of the closed set of length classes")
	case !knownFormats[*wire.Format]:
		return fmt.Errorf("value_shape.format is not one of the closed set of formats")
	case wire.Scheme != nil && !knownSchemeValues[*wire.Scheme]:
		return fmt.Errorf("value_shape.scheme is not one of the closed set of schemes")
	}
	*s = ValueShape{
		Type:        *wire.Type,
		LengthClass: *wire.LengthClass,
		Format:      *wire.Format,
		Present:     *wire.Present,
	}
	if wire.Scheme != nil {
		s.Scheme = *wire.Scheme
	}
	return nil
}

// Valid reports whether every field is in its closed set. For shapes
// built in this binary rather than decoded — a struct literal can put
// any string in a named string type, and the renderer should not have to
// trust that nobody did.
func (s ValueShape) Valid() bool {
	return knownTypes[s.Type] && knownLengthClasses[s.LengthClass] &&
		knownFormats[s.Format] && (s.Scheme == "" || knownSchemeValues[s.Scheme])
}
