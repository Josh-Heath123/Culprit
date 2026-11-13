package probe

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The remaining three probes: configuration presence, dependency version,
// and edge impedance.

// --- probe.config.present ----------------------------------------------

type configPresent struct{}

func (configPresent) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:            "probe.config.present",
		Verdicts:      allVerdicts,
		Discriminates: []string{model.HypothesisConfigMissing},
		// Version 2 (Phase 31.1): measured against `required`, the
		// predicate the config extractors emit for a key the code reads
		// with no default. Version 1 named `is_set`, which no extractor
		// emits, so its expectation could never be found.
		Version:      2,
		Effect:       model.EffectInspect,
		Capabilities: []string{"config.read.names"},
		TimeoutMS:    5_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "config:{component}/{key}", Predicate: model.PredicateRequired},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"key"},
			"properties": map[string]any{
				"key": map[string]any{"type": "string"},
			},
		},
	}
}

func (configPresent) Run(ctx context.Context, request Request, deps Deps) Outcome {
	key, ok := stringInput(request.Inputs, "key")
	if !ok {
		if kind, parts, err := model.ParseSubject(request.Target); err == nil &&
			kind == model.KindConfig {
			key, ok = parts["key"], true
		}
	}
	if !ok {
		return inconclusive("no configuration key was named, so nothing can be checked")
	}
	if deps.Config == nil {
		return inconclusive("this agent cannot see the environment's configuration")
	}
	component := calleeOfTarget(request.Target)

	// `config.read.names` is the whole grant here. The reading records
	// that a key is set, never what it is set to — which is why this
	// probe can run against production without an allowlist.
	present, err := deps.Config.Present(ctx, component, key)
	if err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return inconclusive(fmt.Sprintf(
			"whether %s is set could not be established: %s",
			key, model.RedactCredentials(err.Error())))
	}

	measured := map[string]any{"key": key, "is_set": present}
	if request.Expectation == nil {
		state := "is not set"
		if present {
			state = "is set"
		}
		return withoutExpectation(request, measured,
			fmt.Sprintf("%s %s for %s", key, state, component))
	}

	// `required: true` is "the code reads this key with no default".
	// `required: false` is "it has a default", so an unset key is the
	// default in use, not a fault.
	required, _ := request.Expectation.Value.(bool)
	expected := map[string]any{"required": required}
	source := provenanceOf(request.Expectation)
	if !present && required {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: source,
			Reason: fmt.Sprintf(
				"%s reads %s with no default, and it is not set in this environment",
				component, key),
		}
	}
	return Outcome{Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: source}
}

// --- probe.dep.version -------------------------------------------------

type depVersion struct{}

func (depVersion) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:       "probe.dep.version",
		Verdicts: allVerdicts,
		// Version 2 (Phase 31.1): the expected version comes from the
		// declared dependency when no expect_version is given, and a
		// declared *constraint* is reported as such rather than compared
		// by equality.
		Version:      2,
		Effect:       model.EffectInspect,
		Capabilities: []string{"repo.read"},
		TimeoutMS:    10_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "dep:{component}/{package}", Predicate: model.PredicateVersion},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"package"},
			"properties": map[string]any{
				"package":        map[string]any{"type": "string"},
				"expect_version": map[string]any{"type": "string"},
			},
		},
	}
}

// exactVersion is a declaration that pins one version — `1.2.3`,
// `==1.2.3`, `v1.2.3` — as opposed to a range.
var exactVersion = regexp.MustCompile(`^(==|=)?v?(\d+(\.\d+)*([-+.][0-9A-Za-z.]+)?)$`)

func (depVersion) Run(ctx context.Context, request Request, deps Deps) Outcome {
	name, ok := stringInput(request.Inputs, "package")
	if !ok {
		if kind, parts, err := model.ParseSubject(request.Target); err == nil &&
			kind == model.KindDep {
			name, ok = parts["dependency"], true
		}
	}
	if !ok {
		return inconclusive("no package was named, so no version can be read")
	}
	if deps.Packages == nil {
		return inconclusive("this agent cannot see the environment's installed packages")
	}
	component := calleeOfTarget(request.Target)

	installed, found, err := deps.Packages.Version(ctx, component, name)
	if err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return inconclusive(fmt.Sprintf(
			"the installed version of %s could not be read: %s",
			name, model.RedactCredentials(err.Error())))
	}
	if !found {
		return fail(
			map[string]any{"package": name, "installed": nil},
			fmt.Sprintf("%s is declared as a dependency but is not installed in %s",
				name, component))
	}

	measured := map[string]any{"package": name, "installed": installed}
	// An explicit expect_version is the caller's own, narrower question,
	// and the reading then cites no declaration: expected_source names
	// only a fact the comparison actually used.
	wanted, explicit := stringInput(request.Inputs, "expect_version")
	var source *model.Provenance
	if !explicit && request.Expectation != nil {
		wanted, explicit = request.Expectation.Value.(string)
		source = provenanceOf(request.Expectation)
	}
	if !explicit || wanted == "" {
		return withoutExpectation(request, measured,
			fmt.Sprintf("%s is installed at %s", name, installed))
	}

	// A manifest usually declares a range (`>=0.115`, `^18.2.0`) and an
	// environment has one exact version. Deciding whether one satisfies
	// the other means PEP 440 and semver range semantics, which D7 keeps
	// out of a generic comparator — the same line `culprit env capture`
	// draws (installed_version vs version, docs/LIMITS.md). So a range is
	// reported, not judged.
	pin := exactVersion.FindStringSubmatch(strings.TrimSpace(wanted))
	if pin == nil {
		return Outcome{
			Verdict:        model.VerdictInconclusive,
			Measured:       measured,
			Expected:       map[string]any{"version": wanted},
			ExpectedSource: source,
			Reason: fmt.Sprintf(
				"%s declares %s %s and %s is installed; whether a version satisfies "+
					"a range is not evaluated, only exact pins are compared",
				component, name, wanted, installed),
		}
	}
	expected := map[string]any{"version": wanted}
	if strings.TrimPrefix(installed, "v") != pin[2] {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: source,
			Reason: fmt.Sprintf(
				"%s declares %s at %s but %s is installed",
				component, name, wanted, installed),
		}
	}
	return Outcome{Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: source}
}

// --- probe.edge.impedance ----------------------------------------------

// MinimumImpedanceSamples is how much history the scorer needs before a
// deviation means anything.
//
// Below this the probe returns inconclusive rather than a verdict. A
// z-score over four observations is arithmetic, not evidence, and a
// diagnostic tool that reports it as a finding has started guessing —
// which is the thing this architecture exists not to do.
const MinimumImpedanceSamples = 30

// ImpedanceThreshold is the deviation above which a connection is called
// anomalous. It matches `worker/app/anomaly/scorer.py`'s ANOMALY_THRESHOLD
// deliberately: two different answers to "is this unusual" would be worse
// than either.
const ImpedanceThreshold = 3.0

type edgeImpedance struct{}

func (edgeImpedance) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:       "probe.edge.impedance",
		Verdicts: allVerdicts,
		Version:  1,
		// observe, not inspect: this reads telemetry that already exists
		// rather than touching the system under test at all.
		Effect:       model.EffectObserve,
		Capabilities: []string{"telemetry.metrics.read"},
		TimeoutMS:    15_000,
		// No expectation plane. Impedance is the OBSERVED-plane answer to
		// "deviation from usual", and "usual" is a statistic over
		// OBSERVED, never a fourth plane and never a claim about what is
		// correct.
		ExpectedFrom: "",
		Produces: []model.Produces{
			{SubjectTemplate: "connection:{from}->{to}", Predicate: "impedance"},
		},
		Cost:   model.CostCheap,
		Inputs: map[string]any{"type": "object", "properties": map[string]any{}},
	}
}

func (edgeImpedance) Run(ctx context.Context, request Request, deps Deps) Outcome {
	if deps.Metrics == nil {
		return inconclusive(
			"this agent cannot read telemetry; impedance is scored by Culprit's " +
				"worker, from the telemetry it ingests, and stored as a reading there")
	}
	kind, _, err := model.ParseSubject(request.Target)
	if err != nil || kind != model.KindConnection {
		return inconclusive(
			"impedance is a property of a connection; this target is not one")
	}

	sample, found, err := deps.Metrics.Impedance(ctx, request.Target)
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"impedance for this connection could not be read: %s",
			model.RedactCredentials(err.Error())))
	}
	if !found {
		return inconclusive(
			"no impedance has been scored for this connection; either nothing has " +
				"been observed on it or the anomaly job has not run")
	}
	if sample.Samples < MinimumImpedanceSamples {
		return inconclusive(fmt.Sprintf(
			"only %d observations on this connection, below the %d needed before a "+
				"deviation means anything", sample.Samples, MinimumImpedanceSamples))
	}

	measured := map[string]any{
		"metric":    sample.Metric,
		"deviation": sample.Deviation,
		"samples":   sample.Samples,
	}
	if absFloat(sample.Deviation) >= ImpedanceThreshold {
		return fail(measured, fmt.Sprintf(
			"%s on this connection is %.1f standard deviations from its own "+
				"history", sample.Metric, sample.Deviation))
	}
	return pass(measured)
}

func absFloat(value float64) float64 {
	if value < 0 {
		return -value
	}
	return value
}
