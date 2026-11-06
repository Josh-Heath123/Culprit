package agent

import (
	"errors"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/capability"
)

const validConfig = `version: 1
agent_id: prod-eu-1
manifest: ./culprit.yaml
environments:
  production:
    grants:
      net.dns.resolve: true
      net.tcp.connect: true
      config.read.names: true
      config.inspect.values: [order-service/INVENTORY_TOKEN]
`

func TestAValidConfigurationParses(t *testing.T) {
	config, err := ParseConfig("/etc/culprit/agent.yaml", []byte(validConfig))
	if err != nil {
		t.Fatal(err)
	}
	if config.AgentID != "prod-eu-1" || !strings.HasSuffix(strings.ReplaceAll(config.Manifest, "\\", "/"), "/etc/culprit/culprit.yaml") {
		t.Errorf("config = %+v", config)
	}
	grants := config.Environments["production"]
	if !grants.Has(capability.NetTCPConnect) || !grants.Allows(capability.ConfigInspectValues, "order-service/INVENTORY_TOKEN") {
		t.Errorf("grants not read: %v", grants.Names())
	}
	if grants.Has(capability.ConfigReadValues) {
		t.Error("config.read.values granted though not written")
	}
}

// The refusals the brief names, each with its line: a wildcard, `all`, an
// unknown grant. And their neighbours: a wildcard or `all` as a value or
// an item, a *.write, an unknown key.
func TestTheParserRefusesWildcardsAllAndUnknownGrantsNamingTheLine(t *testing.T) {
	cases := []struct {
		name, line, want string
		atLine           int
	}{
		{"a wildcard capability", "      net.*: true", "wildcard", 7},
		{"a bare wildcard", `      "*": true`, "wildcard", 7},
		{"all as a capability", "      all: true", "no `all`", 7},
		{"an unknown grant", "      net.tcp.conect: true", "not a capability", 7},
		{"all as a value", "      config.inspect.values: all", "grants nothing by name", 7},
		{"a wildcard item", `      config.inspect.values: ["order-service/*"]`, "wildcards", 7},
		{"all as an item", "      config.inspect.values: [all]", "wildcards and `all`", 7},
		{"a write capability", "      db.schema.write: true", "no write capability", 7},
		{"true for a per-item grant", "      db.rows.read: true", "explicit list", 7},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			text := strings.Replace(validConfig, "      net.dns.resolve: true\n", testCase.line+"\n", 1)
			_, err := ParseConfig("agent.yaml", []byte(text))
			var configErr *ConfigError
			if !errors.As(err, &configErr) {
				t.Fatalf("err = %v, want a ConfigError", err)
			}
			if configErr.Line != testCase.atLine {
				t.Errorf("line %d, want %d (%v)", configErr.Line, testCase.atLine, err)
			}
			if !strings.Contains(err.Error(), testCase.want) {
				t.Errorf("err = %q, want it to say %q", err, testCase.want)
			}
			if !strings.Contains(err.Error(), "agent.yaml:7:") {
				t.Errorf("err = %q does not lead with file:line", err)
			}
		})
	}
}

func TestTheParserRefusesAWildcardEnvironmentAndUnknownKeys(t *testing.T) {
	for name, text := range map[string]string{
		"a wildcard environment": strings.Replace(validConfig, "  production:", `  "*":`, 1),
		"an unknown key":         validConfig + "trust_server: true\n",
		"no version":             strings.Replace(validConfig, "version: 1\n", "", 1),
		"no agent id":            strings.Replace(validConfig, "agent_id: prod-eu-1\n", "", 1),
		"no environments":        "version: 1\nagent_id: a\nmanifest: m.yaml\n",
	} {
		if _, err := ParseConfig("agent.yaml", []byte(text)); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestNarrowingCanWithholdAGrantButNeverAddOne(t *testing.T) {
	config, err := ParseConfig("agent.yaml", []byte(validConfig))
	if err != nil {
		t.Fatal(err)
	}
	held := config.Environments["production"]

	narrowed, ignored := held.Narrow([]string{"net.dns.resolve", "net.http.outbound", "db.rows.read"})
	if strings.Join(narrowed.Names(), ",") != "net.dns.resolve" {
		t.Errorf("narrowed to %v, want only net.dns.resolve", narrowed.Names())
	}
	if strings.Join(ignored, ",") != "db.rows.read,net.http.outbound" {
		t.Errorf("ignored %v: the allowance asked for two grants the agent does not hold", ignored)
	}
	if same, _ := held.Narrow(nil); strings.Join(same.Names(), ",") != strings.Join(held.Names(), ",") {
		t.Error("a nil allowance narrowed something")
	}
	if none, _ := held.Narrow([]string{}); len(none.Names()) != 0 {
		t.Errorf("an empty allowance left %v", none.Names())
	}
	keepsItems, _ := held.Narrow([]string{"config.inspect.values"})
	if !keepsItems.Allows(capability.ConfigInspectValues, "order-service/INVENTORY_TOKEN") ||
		keepsItems.Allows(capability.ConfigInspectValues, "order-service/OTHER") {
		t.Error("narrowing changed an allowlist")
	}
}

func TestAYAMLSyntaxErrorNamesItsLineButNotItsText(t *testing.T) {
	text := "version: 1\nagent_id: a\nmanifest: m.yaml\nenvironments:\n  production:\n    grants: [unclosed sk-secret\n"
	_, err := ParseConfig("agent.yaml", []byte(text))
	var configErr *ConfigError
	if !errors.As(err, &configErr) || configErr.Line == 0 {
		t.Fatalf("err = %v, want a line", err)
	}
	if strings.Contains(err.Error(), "sk-secret") {
		t.Errorf("the error quotes the file: %v", err)
	}
}
