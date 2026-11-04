package model

import "fmt"

// ConnectionKind is how one component reaches another. A closed set, the
// same one Python's culprit_model.graph.ConnectionKind and the database's
// ck_connections_kind CHECK hold, kept in agreement by
// shared/tests/connection_kind_conformance.json.
//
// Closed because the kind is what selects a probe: a free-form string
// would let a typo (`queue` for `message`) load and then quietly match no
// probe at all, so the edge would never be examined.
type ConnectionKind string

const (
	ConnectionHTTP    ConnectionKind = "http"
	ConnectionGRPC    ConnectionKind = "grpc"
	ConnectionSQL     ConnectionKind = "sql"
	ConnectionMessage ConnectionKind = "message"
	ConnectionCache   ConnectionKind = "cache"
	ConnectionDNS     ConnectionKind = "dns"
	ConnectionAuth    ConnectionKind = "auth"
)

// DefaultConnectionKind is the kind of an edge whose manifest entry names
// none, matching the Python model's default.
const DefaultConnectionKind = ConnectionHTTP

// ConnectionKinds is every kind, in the fixture's order.
var ConnectionKinds = []ConnectionKind{
	ConnectionHTTP, ConnectionGRPC, ConnectionSQL, ConnectionMessage,
	ConnectionCache, ConnectionDNS, ConnectionAuth,
}

// ParseConnectionKind accepts exactly a member of ConnectionKinds, and
// the empty string as DefaultConnectionKind. Anything else is an error:
// no case folding and no trimming, because Python and the database do
// neither.
func ParseConnectionKind(value string) (ConnectionKind, error) {
	if value == "" {
		return DefaultConnectionKind, nil
	}
	for _, kind := range ConnectionKinds {
		if string(kind) == value {
			return kind, nil
		}
	}
	return "", fmt.Errorf("connection kind %q is not one of %v", value, ConnectionKinds)
}
