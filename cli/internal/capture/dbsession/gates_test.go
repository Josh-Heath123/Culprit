package dbsession

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// The gates that make the statement and plan probes inconclusive: the
// extension absent, the server too old for a plan, the extension present
// but not preloaded. The probes' fixtures inject these messages; these tests
// hold the code that writes them (phase-auditor, 2026-11-13).

// oneRow is the version and extension row statsProbeStatement returns.
type oneRow struct {
	version int
	present bool
	read    bool
}

func (r *oneRow) Close()                                       {}
func (r *oneRow) Err() error                                   { return nil }
func (r *oneRow) CommandTag() pgconn.CommandTag                { return pgconn.CommandTag{} }
func (r *oneRow) FieldDescriptions() []pgconn.FieldDescription { return nil }
func (r *oneRow) Values() ([]any, error)                       { return []any{r.version, r.present}, nil }
func (r *oneRow) RawValues() [][]byte                          { return nil }
func (r *oneRow) Conn() *pgx.Conn                              { return nil }
func (r *oneRow) Next() bool {
	if r.read {
		return false
	}
	r.read = true
	return true
}
func (r *oneRow) Scan(dest ...any) error {
	if len(dest) != 2 {
		return fmt.Errorf("scan into %d", len(dest))
	}
	*dest[0].(*int) = r.version
	*dest[1].(*bool) = r.present
	return nil
}

type rowSession struct {
	row  oneRow
	sent []string
}

func (s *rowSession) Query(_ context.Context, sql string, _ ...any) (pgx.Rows, error) {
	s.sent = append(s.sent, sql)
	row := s.row
	return &row, nil
}

func TestTheStatisticsGates(t *testing.T) {
	for _, c := range []struct {
		name    string
		version int
		present bool
		minimum int
		missing string
	}{
		{"no extension", 160004, false, MinimumPlanVersion, "pg_stat_statements is not installed in this database"},
		{"a plan before 16", 150008, true, MinimumPlanVersion, "PostgreSQL 15 is before 16"},
		{"a plan on 16", 160004, true, MinimumPlanVersion, ""},
		{"a window before its floor", 130000, true, minimumStatsVersion,
			fmt.Sprintf("PostgreSQL 13 is before %d", minimumStatsVersion/10000)},
		{"a window at its floor", minimumStatsVersion, true, minimumStatsVersion, ""},
	} {
		session := &rowSession{row: oneRow{version: c.version, present: c.present}}
		version, missing, err := probeStats(context.Background(), session, c.minimum)
		if err != nil || version != c.version || missing != c.missing {
			t.Errorf("%s: %d %q %v, want %d %q", c.name, version, missing, err, c.version, c.missing)
		}
		if len(session.sent) != 1 || session.sent[0] != string(statsProbeStatement) {
			t.Errorf("%s: sent %q, want only the version and extension template", c.name, session.sent)
		}
	}
	if MinimumPlanVersion != 160000 {
		t.Errorf("MinimumPlanVersion is %d; the brief's floor is PostgreSQL 16", MinimumPlanVersion)
	}
}

func TestAnUnloadedExtensionIsRecognised(t *testing.T) {
	if !unloaded(fmt.Errorf("reading: %w", &pgconn.PgError{Code: "55000"})) {
		t.Error("SQLSTATE 55000 was not read as pg_stat_statements not preloaded")
	}
	for _, err := range []error{&pgconn.PgError{Code: "42P01"}, errors.New("55000"), nil} {
		if unloaded(err) {
			t.Errorf("%v was read as not preloaded", err)
		}
	}
	if strings.TrimSpace(string(statsProbeStatement)) == "" {
		t.Fatal("no version and extension template")
	}
}
