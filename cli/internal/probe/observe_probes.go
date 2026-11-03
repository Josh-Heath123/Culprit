package probe

import (
	"context"
	"fmt"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The remaining three probes: configuration presence, dependency version,
// and edge impedance.

// --- probe.config.present ----------------------------------------------

type configPresent struct{}

func (configPresent) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.config.present",
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"config.read.names"},
		TimeoutMS:    5_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "config:{component}/{key}", Predicate: "is_set"},
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
		return inconclusive("no configuration key was named, so nothing can be checked")
	}
	if deps.Config == nil {
		return inconclusive("this agent cannot see the environment's configuration")
	}
	component := componentOf(request.Target)

	// `config.read.names` is the whole grant here. The reading records
	// that a key is set, never what it is set to — which is why this
	// probe can run against production without an allowlist.
	present, err := deps.Config.Present(ctx, component, key)
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"whether %s is set could not be established: %s",
			key, model.RedactCredentials(err.Error())))
	}

	measured := map[string]any{"key": key, "is_set": present}
	expected := map[string]any{"is_set": true}
	if !present {
		// "reads it with no default" is a claim about the code, which only
		// an INTENT fact can support. Without one, all this probe knows is
		// that a key someone asked about is unset.
		if request.Expectation == nil {
			return inconclusive(fmt.Sprintf(
				"%s is not set for %s, but no INTENT fact says it is required, "+
					"so whether that matters cannot be established here",
				key, component))
		}
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason: fmt.Sprintf(
				"%s reads %s with no default, and it is not set in this environment",
				component, key),
		}
	}
	return Outcome{
		Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation),
	}
}

// --- probe.dep.version -------------------------------------------------

type depVersion struct{}

func (depVersion) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.dep.version",
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"repo.read"},
		TimeoutMS:    10_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "dep:{component}/{package}", Predicate: "version"},
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

func (depVersion) Run(ctx context.Context, request Request, deps Deps) Outcome {
	name, ok := stringInput(request.Inputs, "package")
	if !ok {
		return inconclusive("no package was named, so no version can be read")
	}
	if deps.Packages == nil {
		return inconclusive("this agent cannot see the environment's installed packages")
	}
	component := componentOf(request.Target)

	installed, found, err := deps.Packages.Version(ctx, component, name)
	if err != nil {
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
	wanted, hasExpectation := stringInput(request.Inputs, "expect_version")
	if !hasExpectation {
		return inconclusive(fmt.Sprintf(
			"%s is installed at %s, but no expected version was declared, so "+
				"there is nothing to compare it against", name, installed))
	}

	expected := map[string]any{"version": wanted}
	if installed != wanted {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason: fmt.Sprintf(
				"%s declares %s at %s but %s is installed",
				component, name, wanted, installed),
		}
	}
	return Outcome{
		Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation),
	}
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
		ID:      "probe.edge.impedance",
		Version: 1,
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
		return inconclusive("this agent cannot read telemetry")
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
