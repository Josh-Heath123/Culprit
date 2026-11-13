package extract

// The schema database rule (Q34, PERFORMANCE_PLAN.md, end of Phase 37).
//
// A component's schema facts — the tables its code expects, the indexes its
// migrations declare, the tables a live capture reads — are on
// `schema:<database>/...` subjects. Which database is derived from the
// model, here:
//
//   - the component it connects to by its one `sql` edge;
//   - with no `sql` edge, `<component>-db`;
//   - with two or more, `<component>-db` as well, and the walk cannot join
//     that component's schema facts to either database (docs/LIMITS.md).
//
// The orchestrator sends the name to every extractor (ExtractorRequest.
// Database), capture and the probes use it through DatabaseSpec.DatabaseName,
// environments are refused when their database.name disagrees with it, and
// severity's owner lookup is its inverse (severity.BuildGraph). The API's
// manifest reader refuses the same names (api/app/model/manifest.py, Q28).
//
// Before this, four readers each applied `<component>-db` on their own, so a
// demo whose graph says inventory-service -> inventory-db had its migrations
// on inventory-service-db, and they joined nothing.

// sqlEdge is the kind of connection a component reads its database by.
const sqlEdge = "sql"

// SchemaDatabase is the database component's schema facts are on.
func (m *Manifest) SchemaDatabase(component string) string {
	if m != nil {
		if found, ok := m.componentNamed(component); ok {
			var targets []string
			for _, connection := range found.Connections {
				if connection.Kind == sqlEdge {
					targets = append(targets, connection.To)
				}
			}
			if len(targets) == 1 {
				return targets[0]
			}
		}
	}
	return component + "-db"
}
