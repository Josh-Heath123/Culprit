package isolate

import (
	"fmt"
	"strings"
	"unicode"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The walk's words. A statement, a hypothesis's reason or a rubric reason
// is read by a person, so it names things the way a person would: a kind
// by its label from the shared map (model.HypothesisLabels), a subject by
// what it is. The subject URI itself stays in the investigation's
// structured fields (root_subject, the tree), where it is exact.

// kindPhrase is a hypothesis kind's label, for use mid-sentence: the
// first word lower-cased unless it is an acronym ("TLS certificate
// invalid" stays as it is). A kind with no label — which
// TestEveryKindHasALabel prevents — reads as its words, never as the
// identifier.
func kindPhrase(kind string) string {
	label := model.HypothesisLabels[kind]
	if label == "" {
		label = strings.ReplaceAll(kind, "_", " ")
	}
	if label == "" {
		return "an unnamed explanation"
	}
	first, rest, _ := strings.Cut(label, " ")
	if isAcronym(first) {
		return label
	}
	lowered := strings.ToLower(first[:1]) + first[1:]
	if rest == "" {
		return lowered
	}
	return lowered + " " + rest
}

func isAcronym(word string) bool {
	if len(word) < 2 {
		return false
	}
	for _, r := range word {
		if !unicode.IsUpper(r) && !unicode.IsDigit(r) {
			return false
		}
	}
	return true
}

// describe is a subject as words: "the connection from order-service to
// inventory-service", "PAYMENTS_PROVIDER_KEY in payments-service's
// configuration". A subject it cannot parse is returned as it is.
func describe(subject string) string {
	kind, parts, err := model.ParseSubject(subject)
	if err != nil {
		return subject
	}
	switch kind {
	case model.KindComponent:
		return parts["name"]
	case model.KindConnection:
		return fmt.Sprintf("the connection from %s to %s", parts["from_component"], parts["to_component"])
	case model.KindAuth:
		if parts["aspect"] == "audience" {
			return fmt.Sprintf("the token audience %s presents to %s", parts["from_component"], parts["to_component"])
		}
		return fmt.Sprintf("the credentials %s presents to %s", parts["from_component"], parts["to_component"])
	case model.KindConfig:
		return fmt.Sprintf("%s in %s's configuration", parts["key"], parts["component"])
	case model.KindHTTP:
		return fmt.Sprintf("%s %s on %s", parts["method"], parts["path"], parts["component"])
	case model.KindSchema:
		return fmt.Sprintf("table %s in database %s", parts["table"], parts["database"])
	case model.KindDep:
		return fmt.Sprintf("%s's dependency %s", parts["component"], parts["dependency"])
	case model.KindImage:
		return parts["component"] + "'s image"
	}
	return subject
}

// Describe is describe, for the other packages that write a subject for a
// person to read (internal/verify): one phrasing, never two.
func Describe(subject string) string { return describe(subject) }

// couldNotCheck is one alternative the walk could not test, as a clause
// of a statement: "auth audience mismatch on the token audience
// order-service presents to inventory-service: <why>".
func couldNotCheck(h model.Hypothesis) string {
	return kindPhrase(h.Kind) + " on " + describe(h.Subject) + ": " + h.Reason
}
