// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package model

import "strings"

// Where a CONFIGURED key was read from, by its provenance artefact (Q47,
// Phase 44 batch 3).
//
// A Kubernetes capture is never complete (F44-013): the Deployment's
// template is not the whole environment. But incompleteness is about what
// Culprit could not see, and must never hide what it did see. So the
// adapter names each key's source — the template, or a ConfigMap or
// Secret the template loads with envFrom — and a comparison of two
// captures reads it:
//
//   - a key one template lists and the other does not is a difference,
//     worded as a change to the template;
//   - a key on one side only that came from a source loaded by reference
//     is compared only when the other capture shows a reading of that
//     same source. From a source it did not read, never.
//
// Python's twin is in shared/culprit_model/capture_diff.py; both are held
// to shared/tests/capture_diff_conformance.json.

const (
	// ArtefactKubernetesTemplate prefixes a key the Deployment's template
	// lists itself (`env:`), followed by the Deployment's name.
	ArtefactKubernetesTemplate = "kubernetes:deployment/"
	// ArtefactKubernetesConfigMap and ArtefactKubernetesSecret prefix a key
	// loaded with envFrom, followed by the object's name.
	ArtefactKubernetesConfigMap = "kubernetes:configmap/"
	ArtefactKubernetesSecret    = "kubernetes:secret/"
	artefactKubernetes          = "kubernetes:"
)

// ListedByTemplate says whether a key was read from a Deployment's own
// template.
func ListedByTemplate(artefact string) bool {
	return strings.HasPrefix(artefact, ArtefactKubernetesTemplate)
}

// LoadedByReference says whether a key was read from a source the
// workload loads by reference, so that another capture's silence about it
// means something only if that capture read the same source.
func LoadedByReference(artefact string) bool {
	return strings.HasPrefix(artefact, ArtefactKubernetesConfigMap) ||
		strings.HasPrefix(artefact, ArtefactKubernetesSecret)
}

// ReadFromKubernetes says whether a fact came from a Kubernetes capture.
func ReadFromKubernetes(artefact string) bool {
	return strings.HasPrefix(artefact, artefactKubernetes)
}
