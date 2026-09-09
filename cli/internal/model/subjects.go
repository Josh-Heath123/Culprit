package model

import (
	"fmt"
	"sort"
	"strings"
)

// Subject URIs — the join key of the whole model (§2.3).
//
// BuildSubject is the *only* sanctioned way to construct one on the Go
// side, exactly as culprit_model.subjects.build() is on the Python side.
// Comparison only works if two sources describing the same thing produce
// the same string, and the single reliable way to guarantee that is to
// have one function per language that knows the format, both held to
// shared/tests/subject_conformance.json.
//
//	component:orders-svc
//	connection:orders-svc->payments-svc
//	http:orders-svc/POST /api/v1/orders
//	http:orders-svc/POST /api/v1/orders#request.body
//	config:orders-svc/DATABASE_URL
//	schema:orders-db/public.orders
//	schema:orders-db/public.orders.total_cents
//	dep:orders-svc/stripe
//	image:orders-svc
//	auth:orders-svc->payments-svc/audience

// SubjectKind is the scheme of a subject URI. A closed set: an unknown
// scheme is an error, never a passthrough.
type SubjectKind string

const (
	KindComponent  SubjectKind = "component"
	KindConnection SubjectKind = "connection"
	KindHTTP       SubjectKind = "http"
	KindConfig     SubjectKind = "config"
	KindSchema     SubjectKind = "schema"
	KindDep        SubjectKind = "dep"
	KindImage      SubjectKind = "image"
	KindAuth       SubjectKind = "auth"
)

// arrow is the from->to separator inside a connection/auth subject. A
// component name can never contain it, which is what makes ParseSubject
// unambiguous.
const arrow = "->"

// SubjectError is returned for a subject that cannot be built or parsed.
//
// Deliberately loud. A silently-mangled subject is worse than an error:
// it produces a Fact that will never compare equal to the thing it is
// actually about, and the resulting "no divergence found" is a false
// negative nobody investigates.
type SubjectError struct{ Message string }

func (e *SubjectError) Error() string { return e.Message }

func subjectErrorf(format string, args ...any) error {
	return &SubjectError{Message: fmt.Sprintf(format, args...)}
}

// Characters that mean something structural inside a subject, per part.
// A part containing one of its own separators is rejected rather than
// embedded: BuildSubject(KindHTTP, Parts{"component": "ns/orders", ...})
// would otherwise produce `http:ns/orders/GET /x`, which parses back as
// component "ns" and method "orders/GET" without raising anything.
//
// Tokens, not characters: the connection separator is the two-character
// "->", and forbidding "-" on its own would reject "orders-svc".
var (
	arrowSeparated = []string{"/", arrow, aspectSeparator, " "}
	dotSeparated   = []string{"/", ".", aspectSeparator, " "}

	forbiddenInPart = map[string][]string{
		"name":           arrowSeparated,
		"component":      arrowSeparated,
		"from_component": arrowSeparated,
		"to_component":   arrowSeparated,
		"database":       arrowSeparated,
		// `/` is deliberately absent, unlike every other name-shaped
		// part: ParseSubject cuts on the *first* `/`, so
		// `dep:web/@babel/parser` round-trips exactly. Forbidding it
		// dropped every scoped npm package and Go module path.
		"dependency": {arrow, aspectSeparator, " "},
		"key":        {"/", aspectSeparator, " "},
		"namespace":  dotSeparated,
		"table":      dotSeparated,
		"column":     dotSeparated,
		"aspect":     {"/", aspectSeparator, " "},
	}

	requiredParts = map[SubjectKind][]string{
		KindComponent:  {"name"},
		KindConnection: {"from_component", "to_component"},
		KindHTTP:       {"component", "method", "path"},
		KindConfig:     {"component", "key"},
		KindSchema:     {"database", "table"},
		KindDep:        {"component", "dependency"},
		KindImage:      {"component"},
		KindAuth:       {"from_component", "to_component", "aspect"},
	}

	optionalParts = map[SubjectKind][]string{
		KindHTTP:   {"aspect"},
		KindSchema: {"namespace", "column"},
	}
)

// Parts are the named pieces of a subject, matching the Python
// implementation's keyword arguments one for one.
type Parts map[string]string

// BuildSubject constructs a canonical subject URI.
//
// Every part is canonicalised on the way in, so a caller passing
// "Order-Service" and one passing "order-service" produce the same
// subject. Unknown, missing, or separator-bearing parts return a
// SubjectError rather than a subject that looks well-formed and parses
// back into something else.
func BuildSubject(kind SubjectKind, parts Parts) (string, error) {
	required, known := requiredParts[kind]
	if !known {
		return "", subjectErrorf("unknown subject kind %q", string(kind))
	}

	allowed := map[string]bool{}
	for _, name := range required {
		allowed[name] = true
	}
	for _, name := range optionalParts[kind] {
		allowed[name] = true
	}

	var unexpected []string
	for name := range parts {
		if !allowed[name] {
			unexpected = append(unexpected, name)
		}
	}
	if len(unexpected) > 0 {
		sort.Strings(unexpected)
		return "", subjectErrorf("%s: unexpected part(s) %v", kind, unexpected)
	}

	var missing []string
	for _, name := range required {
		if strings.TrimSpace(parts[name]) == "" {
			missing = append(missing, name)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return "", subjectErrorf("%s: missing required part(s) %v", kind, missing)
	}

	// Checked against the *trimmed* value: surrounding whitespace is
	// something every builder strips anyway, whereas a space *inside* a
	// component name would break the "METHOD path" split.
	for name, value := range parts {
		candidate := strings.TrimSpace(value)
		var offending []string
		for _, token := range forbiddenInPart[name] {
			if strings.Contains(candidate, token) {
				offending = append(offending, token)
			}
		}
		if len(offending) > 0 {
			sort.Strings(offending)
			return "", subjectErrorf(
				"%s: part %s=%q contains subject separator(s) %v — it would parse back as something else",
				kind, name, value, offending)
		}
	}

	switch kind {
	case KindComponent:
		return "component:" + CanonicalComponent(parts["name"]), nil
	case KindConnection:
		return "connection:" + CanonicalComponent(parts["from_component"]) + arrow +
			CanonicalComponent(parts["to_component"]), nil
	case KindHTTP:
		subject := "http:" + CanonicalComponent(parts["component"]) + "/" +
			CanonicalMethod(parts["method"]) + " " + CanonicalPath(parts["path"])
		if aspect := strings.TrimSpace(parts["aspect"]); aspect != "" {
			subject += aspectSeparator + aspect
		}
		return subject, nil
	case KindConfig:
		// The key is trimmed but not case-folded: environment variable
		// names are case-sensitive on every platform this runs on, and
		// folding them would merge two distinct keys into one subject.
		return "config:" + CanonicalComponent(parts["component"]) + "/" +
			strings.TrimSpace(parts["key"]), nil
	case KindSchema:
		namespace := strings.TrimSpace(parts["namespace"])
		if namespace == "" {
			namespace = "public"
		}
		dotted := CanonicalIdentifier(namespace) + "." + CanonicalIdentifier(parts["table"])
		if column := strings.TrimSpace(parts["column"]); column != "" {
			dotted += "." + CanonicalIdentifier(column)
		}
		return "schema:" + CanonicalComponent(parts["database"]) + "/" + dotted, nil
	case KindDep:
		return "dep:" + CanonicalComponent(parts["component"]) + "/" +
			CanonicalComponent(parts["dependency"]), nil
	case KindImage:
		return "image:" + CanonicalComponent(parts["component"]), nil
	case KindAuth:
		return "auth:" + CanonicalComponent(parts["from_component"]) + arrow +
			CanonicalComponent(parts["to_component"]) + "/" + strings.TrimSpace(parts["aspect"]), nil
	}
	return "", subjectErrorf("unknown subject kind %q", string(kind))
}

// MustBuildSubject is BuildSubject for call sites where the parts are
// literals and a failure is a programming error, not input. Used only in
// tests and in code paths that have already validated their inputs.
func MustBuildSubject(kind SubjectKind, parts Parts) string {
	subject, err := BuildSubject(kind, parts)
	if err != nil {
		panic(err)
	}
	return subject
}

// ParseSubject is the inverse of BuildSubject, for reporting and
// severity computation.
//
// BuildSubject(ParseSubject(s)) returns s for every subject BuildSubject
// produced — asserted as a round-trip property over the conformance
// fixture, which is what keeps the two halves from drifting apart.
func ParseSubject(subject string) (SubjectKind, Parts, error) {
	scheme, rest, found := strings.Cut(subject, ":")
	if !found {
		return "", nil, subjectErrorf("not a subject URI (no scheme): %q", subject)
	}
	kind := SubjectKind(scheme)
	if _, known := requiredParts[kind]; !known {
		return "", nil, subjectErrorf("unknown subject kind %q in %q", scheme, subject)
	}

	switch kind {
	case KindComponent, KindImage:
		if rest == "" {
			return "", nil, subjectErrorf("empty component name in %q", subject)
		}
		if kind == KindComponent {
			return kind, Parts{"name": rest}, nil
		}
		return kind, Parts{"component": rest}, nil

	case KindConnection:
		from, to, err := splitArrow(rest, subject)
		if err != nil {
			return "", nil, err
		}
		return kind, Parts{"from_component": from, "to_component": to}, nil

	case KindHTTP:
		component, remainder, found := strings.Cut(rest, "/")
		if !found {
			return "", nil, subjectErrorf("expected 'component/METHOD path' in %q", subject)
		}
		remainder, aspect, hasAspect := strings.Cut(remainder, aspectSeparator)
		method, path, found := strings.Cut(remainder, " ")
		if !found {
			return "", nil, subjectErrorf("expected 'METHOD path' in %q", subject)
		}
		parts := Parts{"component": component, "method": method, "path": path}
		if hasAspect {
			parts["aspect"] = aspect
		}
		return kind, parts, nil

	case KindConfig:
		component, key, found := strings.Cut(rest, "/")
		if !found || key == "" {
			return "", nil, subjectErrorf("expected 'component/KEY' in %q", subject)
		}
		return kind, Parts{"component": component, "key": key}, nil

	case KindSchema:
		database, dotted, found := strings.Cut(rest, "/")
		if !found {
			return "", nil, subjectErrorf("expected 'database/namespace.table' in %q", subject)
		}
		pieces := strings.Split(dotted, ".")
		parts := Parts{"database": database}
		switch len(pieces) {
		case 2:
			parts["namespace"], parts["table"] = pieces[0], pieces[1]
		case 3:
			parts["namespace"], parts["table"], parts["column"] = pieces[0], pieces[1], pieces[2]
		default:
			return "", nil, subjectErrorf("expected 'namespace.table[.column]' in %q", subject)
		}
		return kind, parts, nil

	case KindDep:
		component, dependency, found := strings.Cut(rest, "/")
		if !found || dependency == "" {
			return "", nil, subjectErrorf("expected 'component/dependency' in %q", subject)
		}
		return kind, Parts{"component": component, "dependency": dependency}, nil

	case KindAuth:
		pair, aspect, found := strings.Cut(rest, "/")
		if !found || aspect == "" {
			return "", nil, subjectErrorf("expected 'from%sto/aspect' in %q", arrow, subject)
		}
		from, to, err := splitArrow(pair, subject)
		if err != nil {
			return "", nil, err
		}
		return kind, Parts{"from_component": from, "to_component": to, "aspect": aspect}, nil
	}
	return "", nil, subjectErrorf("unknown subject kind %q in %q", scheme, subject)
}

func splitArrow(rest, subject string) (string, string, error) {
	from, to, found := strings.Cut(rest, arrow)
	if !found || from == "" || to == "" {
		return "", "", subjectErrorf("expected 'from%sto' in %q", arrow, subject)
	}
	return from, to, nil
}
