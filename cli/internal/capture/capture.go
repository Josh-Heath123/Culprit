// Package capture reads the CONFIGURED plane of one environment
// (Phase 30).
//
// `culprit env capture production` asks one question of a running
// environment — *what is it actually set up to do?* — and answers it as
// CONFIGURED facts that the same generic comparator that finds intent
// conflicts can compare against INTENT and against other environments,
// unchanged in kind (D7). Environment variable names and shapes, image
// references and digests, live table columns and the migration version,
// installed package versions, and whether an endpoint resolves, accepts
// a connection and presents a valid certificate.
//
// # Everything is behind a capability, and every refusal is recorded
//
// Each check asks the capability.Ledger before it looks. What was not
// granted is not silently skipped: it lands in the bundle's `refused`
// list, so a capture says what it did not look at as plainly as what it
// found (field 7). A capture of production that reports nothing wrong
// with the database because it was never allowed near the database must
// say so, or the report is lying by omission.
//
// # What leaves this package
//
// A CaptureBundle whose facts carry config **shapes**, not values —
// except for keys named on a `config.read.values` allowlist, whose facts
// carry the literal *and* the grant that permitted it, which is the only
// form model.Fact.Validate accepts. Every reason string in a skip or a
// refusal is built from closed vocabulary and from names in
// `culprit.yaml`, never from an error message or anything the environment
// returned (standing invariant 11). `capture_test.go` plants a secret in
// every place an environment can hand one over and greps the sealed
// envelope, the rendered text and the JSON for it.
//
// # No requests into the system under test, no writes, no daemon
//
// Field 17. Capture reads configuration and metadata. It sends no
// application request (see network.go for exactly where it stops), it
// opens its database session read-only, and it runs once and exits.
package capture

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Predicates the CONFIGURED plane emits beyond the shared vocabulary in
// model/protocol.go. Plain strings, like every predicate: the comparator
// compares them without knowing what any of them mean.
const (
	PredicateReference        = "reference"
	PredicateDigest           = "digest"
	PredicateImageID          = "image_id"
	PredicateInstalledVersion = "installed_version"
	PredicateDNSResolves      = "dns_resolves"
	PredicatePortReachable    = "port_reachable"
	PredicateTLSCertificate   = "tls_certificate"
	// PredicateValue carries a literal config value, only ever for a key
	// on the `config.read.values` allowlist and only ever with a grant_ref.
	PredicateValue = "value"
)

// Check names. The "check" in a refusal is always one of these, so a
// report can be read, and a refusal compared, without free text.
const (
	CheckEnvironment = "environment variables"
	CheckValues      = "config values"
	CheckImage       = "image"
	CheckSchema      = "live schema"
	CheckPackages    = "installed packages"
	CheckDNS         = "dns"
	CheckPort        = "port"
	CheckTLS         = "tls certificate"
)

// Wants for the skips this package records, alongside the extraction
// wants they share a meaning with.
const (
	WantImage    = "image"
	WantEndpoint = "endpoint"
)

// Options configure one capture.
type Options struct {
	Manifest    *extract.Manifest
	ManifestDir string
	Environment string
	// Only restricts the capture to these components.
	Only    []string
	Now     time.Time
	Version string

	Runner   Runner
	Network  Network
	Database MetadataReader
	// LookupEnv reads culprit's *own* environment — where `dsn_env` names
	// a variable holding a connection string. Never used to read a
	// workload's environment; that is the adapter's job.
	LookupEnv func(string) (string, bool)
	// Environ is what the process adapter reads.
	Environ func() []string
}

// Defaults fills in the real implementations for anything not injected.
func (o Options) withDefaults() Options {
	if o.Runner == nil {
		o.Runner = ExecRunner{}
	}
	if o.Network == nil {
		o.Network = RealNetwork{}
	}
	if o.Database == nil {
		o.Database = PostgresReader{}
	}
	if o.LookupEnv == nil {
		o.LookupEnv = os.LookupEnv
	}
	if o.Environ == nil {
		o.Environ = os.Environ
	}
	if o.Now.IsZero() {
		o.Now = time.Now().UTC()
	}
	return o
}

// Run captures one environment.
//
// It returns an error only when the run as a whole is meaningless — no
// such environment, grants that do not parse. Everything else, down to
// every single check failing, is reported inside the bundle as skips and
// refusals: a capture is most useful precisely when the environment is
// broken, so an environment being broken must not stop it.
func Run(ctx context.Context, options Options) (model.CaptureBundle, error) {
	options = options.withDefaults()
	if options.Manifest == nil {
		return model.CaptureBundle{}, fmt.Errorf("no culprit.yaml was loaded")
	}
	spec, ok := options.Manifest.Environments[options.Environment]
	if !ok {
		names := options.Manifest.EnvironmentNames()
		if len(names) == 0 {
			return model.CaptureBundle{}, fmt.Errorf(
				"culprit.yaml declares no environments; add an `environments:` section " +
					"(see docs/PERMISSIONS.md)")
		}
		return model.CaptureBundle{}, fmt.Errorf("no environment named %q in culprit.yaml (declared: %s)",
			options.Environment, strings.Join(names, ", "))
	}
	grants, err := spec.ParsedGrants()
	if err != nil {
		return model.CaptureBundle{}, err
	}
	adapter, err := NewAdapter(spec, options.ManifestDir, options.Runner, options.Environ)
	if err != nil {
		return model.CaptureBundle{}, err
	}

	components := sortedKeys(spec.Components)
	if len(options.Only) > 0 {
		wanted := map[string]bool{}
		for _, name := range options.Only {
			wanted[model.CanonicalComponent(name)] = true
		}
		filtered := components[:0:0]
		for _, name := range components {
			if wanted[model.CanonicalComponent(name)] {
				filtered = append(filtered, name)
			}
		}
		if len(filtered) == 0 {
			return model.CaptureBundle{}, fmt.Errorf(
				"environment %s captures no component matching %s",
				options.Environment, strings.Join(options.Only, ", "))
		}
		components = filtered
	}

	now := options.Now.UTC()
	run := &runState{
		options:   options,
		spec:      spec,
		grants:    grants,
		ledger:    capability.NewLedger(grants),
		adapter:   adapter,
		now:       now,
		extractor: "culprit@" + options.Version,
		captureID: deriveCaptureID(options.ManifestDir, options.Environment, components, now),
		facts:     []model.Fact{},
		skipped:   []model.Skip{},
		meta: map[string]string{
			"cli_version": options.Version,
			"adapter":     spec.Adapter,
			"components":  strings.Join(components, ","),
		},
	}
	for _, component := range components {
		run.component(ctx, component, spec.Components[component])
	}

	sortFacts(run.facts)
	sort.SliceStable(run.skipped, func(i, j int) bool {
		left, right := run.skipped[i], run.skipped[j]
		if left.Component != right.Component {
			return left.Component < right.Component
		}
		if left.Want != right.Want {
			return left.Want < right.Want
		}
		return left.Reason < right.Reason
	})

	environment := options.Environment
	finished := now
	return model.CaptureBundle{
		Protocol:    model.ExtractorProtocolVersion,
		Plane:       model.PlaneConfigured,
		Environment: &environment,
		Extractor:   run.extractor,
		CaptureID:   run.captureID,
		StartedAt:   now,
		FinishedAt:  &finished,
		Facts:       run.facts,
		Skipped:     run.skipped,
		Meta:        run.meta,
		Grants:      run.ledger.Records(),
		Refused:     run.ledger.Refusals(),
	}, nil
}

type runState struct {
	options   Options
	spec      extract.EnvironmentSpec
	grants    capability.Grants
	ledger    *capability.Ledger
	adapter   Adapter
	now       time.Time
	extractor string
	captureID string
	facts     []model.Fact
	skipped   []model.Skip
	meta      map[string]string
}

func (r *runState) component(ctx context.Context, component string, settings extract.EnvironmentComponent) {
	r.environment(ctx, component, settings)
	r.image(ctx, component, settings)
	r.database(ctx, component, settings)
	r.packages(ctx, component, settings)
	r.endpoint(ctx, component, settings)
}

// --- environment variables -------------------------------------------

func (r *runState) environment(ctx context.Context, component string, settings extract.EnvironmentComponent) {
	if !r.ledger.Require(capability.ConfigReadNames, component, CheckEnvironment) {
		return
	}
	// The exec adapter runs a user-declared command to read the
	// environment, so it needs that command's allowlist entry too.
	//
	// RequireItem records a refusal only when the capability is granted
	// for *some* items; when it is not granted at all, Require is what
	// records one. Asking only RequireItem here left that case as a silent
	// omission — unreachable today, because manifest validation refuses an
	// exec entry nothing may run, but a contradiction of the Ledger's own
	// contract that the next change to validation would have exposed.
	// (Found by the Phase 30 invariant audit.)
	if r.spec.Adapter == extract.AdapterExec {
		if !r.grants.Has(capability.ProcessExecAllowlist) {
			r.ledger.Require(capability.ProcessExecAllowlist, component, CheckEnvironment)
			return
		}
		if !r.ledger.RequireItem(capability.ProcessExecAllowlist, settings.EnvCommand, component, CheckEnvironment) {
			return
		}
	}

	workload, err := r.adapter.Workload(ctx, component, settings)
	if err != nil {
		r.skip(component, string(model.WantConfigKeys), fmt.Sprintf(
			"the %s adapter could not read %s's environment: %s",
			r.adapter.Name(), component, safeReason(err)))
		return
	}
	if !workload.Complete {
		// Recorded as a skip, and the comparator reads it that way: an
		// environment known to have keys this capture could not see must
		// never be the evidence that a key is *absent*.
		r.skip(component, string(model.WantConfigKeys), fmt.Sprintf(
			"%s's environment could not be enumerated completely (%s), so no key is "+
				"judged missing from it", component, strings.Join(workload.Incomplete, "; ")))
	}
	if workload.Replicas > 1 {
		r.meta["replicas."+component] = fmt.Sprintf(
			"%d found; the first by name was read", workload.Replicas)
	}

	provenance := r.provenance(workload.Artefact)
	unlisted, unnamable := 0, 0
	for _, key := range sortedKeys(workload.Env) {
		entry := workload.Env[key]
		shape := model.UnknownShape()
		if entry.Known {
			shape = model.ShapeOfString(entry.Value)
		}
		names := string(capability.ConfigReadNames)
		existsFact, err := r.fact(component, key, model.PredicateExists, true, &names, provenance)
		if err != nil {
			unnamable++
			continue
		}
		shapeFact, _ := model.NewConfigFact(model.PlaneConfigured, component, key,
			model.PredicateValueShape, shape, provenance, r.now, r.captureID)
		shapeFact.Environment = r.options.Environment
		shapeFact.GrantRef = names
		r.facts = append(r.facts, existsFact, shapeFact)

		if !entry.Known {
			continue
		}
		grantItem := component + "/" + key
		if !r.grants.Allows(capability.ConfigReadValues, grantItem) {
			unlisted++
			continue
		}
		r.ledger.RequireItem(capability.ConfigReadValues, grantItem, component, CheckValues)
		grantRef := string(capability.ConfigReadValues) + ":" + grantItem
		if valueFact, err := r.fact(component, key, PredicateValue, entry.Value, &grantRef, provenance); err == nil {
			r.facts = append(r.facts, valueFact)
		}
	}

	if unlisted > 0 {
		reason := fmt.Sprintf("%s is not granted", capability.ConfigReadValues)
		if r.grants.Has(capability.ConfigReadValues) {
			reason = fmt.Sprintf("%s is granted only for other keys", capability.ConfigReadValues)
		}
		r.ledger.Refuse(capability.ConfigReadValues, component, CheckValues, fmt.Sprintf(
			"the values of %d key(s) were not captured — only their shape (%s)", unlisted, reason))
	}
	if unnamable > 0 {
		r.skip(component, string(model.WantConfigKeys), fmt.Sprintf(
			"%d variable(s) have names that cannot form a subject and were not recorded", unnamable))
	}
}

// --- image ------------------------------------------------------------

func (r *runState) image(ctx context.Context, component string, settings extract.EnvironmentComponent) {
	// A plain process and an arbitrary command have no image. Not asked
	// of the ledger at all: a refusal for a check that could never exist
	// in this environment would be noise pretending to be caution.
	if r.spec.Adapter != extract.AdapterCompose && r.spec.Adapter != extract.AdapterKubernetes {
		return
	}
	if !r.ledger.Require(capability.DeployMetadataRead, component, CheckImage) {
		return
	}
	image, err := r.adapter.Image(ctx, component, settings)
	if err != nil {
		r.skip(component, WantImage, fmt.Sprintf(
			"the %s adapter could not read %s's image: %s", r.adapter.Name(), component, safeReason(err)))
		return
	}
	subject, err := model.BuildSubject(model.KindImage, model.Parts{"component": component})
	if err != nil {
		return
	}
	provenance := r.provenance(r.adapter.Name() + ":" + settings.WorkloadFor(component))
	// The local image id only when there is no registry digest. When
	// there is one, the id is a second name for the same content, and
	// emitting both would report one different build as two findings.
	imageID := image.ID
	if image.Digest != "" {
		imageID = ""
	}
	for _, entry := range []struct{ predicate, value string }{
		{PredicateReference, image.Reference},
		{PredicateDigest, image.Digest},
		{PredicateImageID, imageID},
	} {
		if entry.value == "" {
			continue
		}
		r.facts = append(r.facts, r.plainFact(
			subject, entry.predicate, entry.value, capability.DeployMetadataRead, provenance))
	}
	if image.Digest == "" {
		r.skip(component, WantImage, fmt.Sprintf(
			"%s's image has no registry digest (built locally, or its pods report none); "+
				"its local image id is compared instead, which only matches on the same host",
			component))
	}
}

// --- live schema ------------------------------------------------------

func (r *runState) database(ctx context.Context, component string, settings extract.EnvironmentComponent) {
	if settings.Database == nil {
		return
	}
	if !r.ledger.Require(capability.DBMetadataRead, component, CheckSchema) {
		return
	}
	dsn, ok := r.options.LookupEnv(settings.Database.DSNEnv)
	if !ok || strings.TrimSpace(dsn) == "" {
		r.skip(component, string(model.WantDBSchema), fmt.Sprintf(
			"%s is not set in the environment culprit is running in, so %s's database "+
				"was not read", settings.Database.DSNEnv, component))
		return
	}
	schema, err := r.options.Database.Read(ctx, dsn)
	if err != nil {
		r.skip(component, string(model.WantDBSchema), fmt.Sprintf(
			"%s's database was not read: %s", component, safeReason(err)))
		return
	}

	database := settings.Database.DatabaseName(component)
	provenance := r.provenance("postgres:" + database)
	for _, table := range schema.Tables {
		subject, err := model.BuildSubject(model.KindSchema, model.Parts{
			"database": database, "namespace": table.Namespace, "table": table.Table,
		})
		if err != nil {
			continue
		}
		columns := sortedKeys(table.Columns)
		r.facts = append(r.facts, r.plainFact(
			subject, model.PredicateColumns, columns, capability.DBMetadataRead, provenance))
		for _, column := range columns {
			columnSubject, err := model.BuildSubject(model.KindSchema, model.Parts{
				"database": database, "namespace": table.Namespace,
				"table": table.Table, "column": column,
			})
			if err != nil {
				continue
			}
			r.facts = append(r.facts, r.plainFact(columnSubject, model.PredicateNullable,
				table.Columns[column], capability.DBMetadataRead, provenance))
		}
	}

	if !schema.HasAlembic {
		r.skip(component, string(model.WantDBSchema), fmt.Sprintf(
			"%s's database has no alembic_version table, so its migration version is unknown",
			component))
		return
	}
	if schema.VersionUnreadable != "" {
		r.skip(component, string(model.WantDBSchema), fmt.Sprintf(
			"%s's migration version was not read (%s); grant the capture role SELECT on "+
				"alembic_version to include it", component, schema.VersionUnreadable))
		return
	}
	subject, err := model.BuildSubject(model.KindComponent, model.Parts{"name": component})
	if err == nil {
		r.facts = append(r.facts, r.plainFact(subject, model.PredicateMigrationHead,
			schema.MigrationHeads, capability.DBMetadataRead, provenance))
	}
}

// --- installed packages -----------------------------------------------

func (r *runState) packages(ctx context.Context, component string, settings extract.EnvironmentComponent) {
	if settings.Packages == "" {
		return
	}
	if !r.grants.Has(capability.ProcessExecAllowlist) {
		r.ledger.Require(capability.ProcessExecAllowlist, component, CheckPackages)
		return
	}
	if !r.ledger.RequireItem(capability.ProcessExecAllowlist, settings.Packages, component, CheckPackages) {
		return
	}
	out, err := r.options.Runner.Run(ctx, r.spec.Exec[settings.Packages])
	if err != nil {
		r.skip(component, string(model.WantDependencies), fmt.Sprintf(
			"%s's installed packages were not read: %s", component, safeReason(err)))
		return
	}
	versions, ok := parsePackages(out)
	if !ok {
		r.skip(component, string(model.WantDependencies), fmt.Sprintf(
			"the output of %s was neither `pip freeze` nor `npm ls --json`", settings.Packages))
		return
	}
	provenance := r.provenance("exec:" + settings.Packages)
	for _, name := range sortedKeys(versions) {
		subject, err := model.BuildSubject(model.KindDep, model.Parts{
			"component": component, "dependency": name,
		})
		if err != nil {
			continue
		}
		fact := r.plainFact(subject, PredicateInstalledVersion, versions[name],
			capability.ProcessExecAllowlist, provenance)
		fact.GrantRef += ":" + settings.Packages
		r.facts = append(r.facts, fact)
	}
}

// --- endpoint ---------------------------------------------------------

func (r *runState) endpoint(ctx context.Context, component string, settings extract.EnvironmentComponent) {
	endpoint := settings.Endpoint
	if endpoint == nil {
		return
	}
	subject, err := model.BuildSubject(model.KindComponent, model.Parts{"name": component})
	if err != nil {
		return
	}
	provenance := r.provenance(fmt.Sprintf("endpoint:%s:%d", endpoint.Host, endpoint.Port))

	if r.ledger.Require(capability.NetDNSResolve, component, CheckDNS) {
		r.facts = append(r.facts, r.plainFact(subject, PredicateDNSResolves,
			r.options.Network.Resolves(ctx, endpoint.Host), capability.NetDNSResolve, provenance))
	}
	if r.ledger.Require(capability.NetTCPConnect, component, CheckPort) {
		r.facts = append(r.facts, r.plainFact(subject, PredicatePortReachable,
			r.options.Network.Reachable(ctx, endpoint.Host, endpoint.Port),
			capability.NetTCPConnect, provenance))
	}
	if !endpoint.TLS {
		return
	}
	// A TLS handshake is a TCP connection first. Both capabilities, and a
	// refusal that names whichever is missing rather than a generic one.
	var missing []string
	for _, needed := range []capability.Capability{capability.NetTLSInspect, capability.NetTCPConnect} {
		if !r.grants.Has(needed) {
			missing = append(missing, string(needed))
		}
	}
	if len(missing) > 0 {
		r.ledger.Refuse(capability.NetTLSInspect, component, CheckTLS,
			"reading a certificate needs "+strings.Join(missing, " and ")+", which is not granted")
		return
	}
	r.ledger.Require(capability.NetTLSInspect, component, CheckTLS)
	r.facts = append(r.facts, r.plainFact(subject, PredicateTLSCertificate,
		r.options.Network.Certificate(ctx, endpoint.Host, endpoint.Port, r.now),
		capability.NetTLSInspect, provenance))
}

// --- helpers ----------------------------------------------------------

// provenance is the same for every CONFIGURED fact but the artefact.
//
// Rank 90, the runtime-introspection landmark: every one of these was
// read from the thing itself rather than inferred about it. Rank is not
// how completeness is judged — a capture that could not see a whole
// environment records a skip, and the comparator reads the skip.
func (r *runState) provenance(artefact string) model.Provenance {
	return model.Provenance{
		SourceKind:     model.SourceIntrospection,
		Extractor:      r.extractor,
		Artefact:       artefact,
		ConfidenceRank: model.RankRuntimeIntrospection,
	}
}

func (r *runState) fact(
	component, key, predicate string, value any, grantRef *string, provenance model.Provenance,
) (model.Fact, error) {
	subject, err := model.BuildSubject(model.KindConfig, model.Parts{"component": component, "key": key})
	if err != nil {
		return model.Fact{}, err
	}
	fact := model.Fact{
		Plane:       model.PlaneConfigured,
		Subject:     subject,
		Predicate:   predicate,
		Value:       value,
		Environment: r.options.Environment,
		Provenance:  provenance,
		CapturedAt:  r.now,
		CaptureID:   r.captureID,
	}
	if grantRef != nil {
		fact.GrantRef = *grantRef
	}
	return fact, fact.Validate()
}

// plainFact is a non-config CONFIGURED fact, carrying the grant that
// permitted reading it.
//
// # Every CONFIGURED value names its grant
//
// Not only config values. `configured_facts` has carried a CHECK since
// Phase 26.1 — `value IS NULL OR grant_ref IS NOT NULL` — and it covers
// every row, not only `config:` ones, so an image digest or a column list
// with no `grant_ref` cannot be stored at all. That is not a defect to
// work around by narrowing the constraint: every value a capture holds
// *was* read under an explicit grant, and naming it makes each fact say
// what permitted it. `POST /captures` then checks every `grant_ref`
// against the capture's own grant list, which is the validation
// docs/LIMITS.md recorded as missing ("nothing validates that the grant
// it names is real") — now there is a grant list to validate against.
//
// A config value's grant stays per-key (`config.read.values:<component>/<KEY>`),
// exactly as §2.2 requires; everything else names its capability.
func (r *runState) plainFact(
	subject, predicate string, value any, grant capability.Capability, provenance model.Provenance,
) model.Fact {
	return model.Fact{
		Plane:       model.PlaneConfigured,
		Subject:     subject,
		Predicate:   predicate,
		Value:       value,
		GrantRef:    string(grant),
		Environment: r.options.Environment,
		Provenance:  provenance,
		CapturedAt:  r.now,
		CaptureID:   r.captureID,
	}
}

func (r *runState) skip(component, want, reason string) {
	r.skipped = append(r.skipped, model.Skip{
		Want: want, Component: component, Reason: reason, Extractor: r.extractor,
	})
}

// SafeReason is safeReason for `culprit probe`'s data sources (Phase
// 31.1), which use this package's adapters, runner and reader and must
// render their errors under the same closure: an error that is not one of
// the closed kinds below becomes a fixed phrase, never its own text.
func SafeReason(err error) string { return safeReason(err) }

// safeReason renders an error only if it is one of this package's own
// closed kinds; anything else becomes a fixed phrase. See runner.go.
func safeReason(err error) string {
	var runErr *RunError
	var dbErr *DBError
	switch {
	case errors.As(err, &runErr):
		return runErr.Error()
	case errors.As(err, &dbErr):
		return dbErr.Error()
	case errors.Is(err, errNotRunning), errors.Is(err, errUnreadable),
		errors.Is(err, errNoSuchContainer), errors.Is(err, ErrNoImage),
		errors.Is(err, errNotNULOrJSON):
		return err.Error()
	}
	return "an unexpected error"
}

// deriveCaptureID is DeriveCaptureID's shape with the environment in the
// input, so two environments captured in the same second from the same
// checkout are two captures.
func deriveCaptureID(manifestDir, environment string, components []string, now time.Time) string {
	hasher := sha256.New()
	fmt.Fprintf(hasher, "culprit-capture-v1\x00configured\x00%s\x00%s\x00%s\x00",
		manifestDir, environment, now.UTC().Format(time.RFC3339Nano))
	for _, name := range components {
		fmt.Fprintf(hasher, "%s\x00", name)
	}
	sum := hasher.Sum(nil)
	sum[6] = (sum[6] & 0x0f) | 0x50
	sum[8] = (sum[8] & 0x3f) | 0x80
	text := hex.EncodeToString(sum[:16])
	return fmt.Sprintf("%s-%s-%s-%s-%s", text[0:8], text[8:12], text[12:16], text[16:20], text[20:32])
}

func sortFacts(facts []model.Fact) {
	sort.SliceStable(facts, func(i, j int) bool {
		left, right := facts[i], facts[j]
		if left.Subject != right.Subject {
			return left.Subject < right.Subject
		}
		if left.Predicate != right.Predicate {
			return left.Predicate < right.Predicate
		}
		return left.Provenance.Artefact < right.Provenance.Artefact
	})
}
