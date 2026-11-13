package extract

import (
	"strings"
	"testing"
)

// The schema database rule (Q34): derived from the model, and an
// environment's database.name held to it.

const databaseRuleManifest = `version: 1
components:
  - name: shop
    kind: service
    connections:
      - to: shop-store
        kind: sql
      - to: pricing
        kind: http
  - name: shop-store
    kind: database
  - name: pricing
    kind: service
  - name: reports
    kind: service
    connections:
      - to: shop-store
        kind: sql
      - to: warehouse
        kind: sql
  - name: warehouse
    kind: database
`

func TestTheSchemaDatabaseIsDerivedFromTheModel(t *testing.T) {
	manifest, err := LoadManifest(writeManifest(t, databaseRuleManifest))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct{ component, want, why string }{
		{"shop", "shop-store", "one sql edge: its target, whatever its name; the http edge is not counted"},
		{"pricing", "pricing-db", "no sql edge: <component>-db"},
		{"reports", "reports-db", "two sql edges: <component>-db, and nothing joins (LIMITS)"},
		{"undeclared", "undeclared-db", "a component the file does not declare"},
	} {
		if got := manifest.SchemaDatabase(c.component); got != c.want {
			t.Errorf("%s: %q, want %q (%s)", c.component, got, c.want, c.why)
		}
	}
	var nothing *Manifest
	if got := nothing.SchemaDatabase("shop"); got != "shop-db" {
		t.Errorf("no manifest: %q, want shop-db", got)
	}
}

func TestAnEnvironmentsDatabaseNameIsHeldToTheRule(t *testing.T) {
	environment := func(name string) string {
		text := databaseRuleManifest + `environments:
  local:
    adapter: process
    grants: {db.metadata.read: true}
    components:
      shop:
        database:
          dsn_env: SHOP_DSN
`
		if name != "" {
			text += "          name: " + name + "\n"
		}
		return text
	}

	agrees, err := LoadManifest(writeManifest(t, environment("shop-store")))
	if err != nil {
		t.Fatalf("the rule's own name was refused: %v", err)
	}
	if got := agrees.Environments["local"].Components["shop"].Database.DatabaseName(agrees, "shop"); got != "shop-store" {
		t.Errorf("DatabaseName with the rule's name: %q", got)
	}

	omitted, err := LoadManifest(writeManifest(t, environment("")))
	if err != nil {
		t.Fatalf("no name was refused: %v", err)
	}
	if got := omitted.Environments["local"].Components["shop"].Database.DatabaseName(omitted, "shop"); got != "shop-store" {
		t.Errorf("DatabaseName with no name given: %q, want the rule's shop-store, not shop-db", got)
	}

	_, err = LoadManifest(writeManifest(t, environment("shop-db")))
	if err == nil {
		t.Fatal("database.name shop-db was accepted, though shop's one sql edge is to shop-store")
	}
	for _, want := range []string{"environments.local.components.shop.database.name", `"shop-db"`, `"shop-store"`} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("the refusal does not name %s: %v", want, err)
		}
	}
}
