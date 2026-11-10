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

// Phase 33 part 3, carried in: a control plane is reached over https. Plain
// http is refused, naming the line, unless the host is a loopback address
// or the configuration sets allow_plain_http — which the agent then
// reports at every start (cmd/culprit).
func TestPlainHTTPIsRefusedExceptToLoopbackOrWithAllowPlainHTTP(t *testing.T) {
	const key = "key: ./agent.key\n"
	cases := []struct {
		name, controlPlane string
		wantErr            string // "" means it parses
		wantAllow          bool
	}{
		{"https", "control_plane:\n  url: https://culprit.example.com/api\n", "", false},
		{"plain http to a remote host", "control_plane:\n  url: http://culprit.example.com/api\n", "allow_plain_http", false},
		{"plain http to an address that only starts like loopback", "control_plane:\n  url: http://127.0.0.1.example.com/api\n", "allow_plain_http", false},
		{"plain http to a name that only starts like localhost", "control_plane:\n  url: http://localhost.example.com/api\n", "allow_plain_http", false},
		{"plain http to 127.0.0.1", "control_plane:\n  url: http://127.0.0.1:8080/api\n", "", false},
		{"plain http to another 127/8 address", "control_plane:\n  url: http://127.0.0.2/api\n", "", false},
		{"plain http to localhost", "control_plane:\n  url: http://localhost/api\n", "", false},
		{"plain http to ::1", "control_plane:\n  url: http://[::1]:8080/api\n", "", false},
		{"plain http, explicitly allowed", "control_plane:\n  url: http://host.docker.internal/api\n  allow_plain_http: true\n", "", true},
		{"allow_plain_http false is still a refusal", "control_plane:\n  url: http://host.docker.internal/api\n  allow_plain_http: false\n", "allow_plain_http", false},
		{"allow_plain_http must be a boolean", "control_plane:\n  url: http://host.docker.internal/api\n  allow_plain_http: yes please\n", "true or false", false},
		{"allow_plain_http on https is recorded but changes nothing", "control_plane:\n  url: https://culprit.example.com/api\n  allow_plain_http: true\n", "", true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			text := validConfig + testCase.controlPlane + key
			config, err := ParseConfig("/etc/culprit/agent.yaml", []byte(text))
			if testCase.wantErr == "" {
				if err != nil {
					t.Fatalf("refused: %v", err)
				}
				if config.AllowPlainHTTP != testCase.wantAllow {
					t.Errorf("AllowPlainHTTP = %v, want %v", config.AllowPlainHTTP, testCase.wantAllow)
				}
				return
			}
			if err == nil {
				t.Fatalf("accepted %q", testCase.controlPlane)
			}
			var configErr *ConfigError
			if !errors.As(err, &configErr) || configErr.Line != 12 {
				t.Errorf("error does not name line 12, the control_plane block: %v", err)
			}
			if !strings.Contains(err.Error(), testCase.wantErr) {
				t.Errorf("error %q does not mention %q", err, testCase.wantErr)
			}
		})
	}
}
