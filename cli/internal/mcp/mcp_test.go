package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func echoServer(calls *int) *Server {
	return &Server{
		Name: "culprit", Version: "test",
		Tools: []Tool{{
			Name:        "echo",
			Description: "returns its argument",
			Input: Schema{
				Properties: map[string]Property{
					"word":  {Type: String, Description: "a word"},
					"words": {Type: Strings, Description: "words"},
					"mode":  {Type: String, Description: "a mode", Enum: []string{"loud", "quiet"}},
				},
				Required: []string{"word"},
			},
			Annotations: Annotations{ReadOnlyHint: true},
			Handler: func(_ context.Context, arguments map[string]any) Result {
				*calls++
				return Result{Structured: map[string]any{"word": Text(arguments, "word")}}
			},
		}},
	}
}

// exchange sends lines and returns the responses, one per line written.
func exchange(t *testing.T, server *Server, lines ...string) []map[string]any {
	t.Helper()
	var out bytes.Buffer
	if err := server.Run(context.Background(), strings.NewReader(strings.Join(lines, "\n")+"\n"), &out); err != nil {
		t.Fatal(err)
	}
	var replies []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if line == "" {
			continue
		}
		var reply map[string]any
		if err := json.Unmarshal([]byte(line), &reply); err != nil {
			t.Fatalf("a response is not one JSON object per line: %v\n%s", err, out.String())
		}
		replies = append(replies, reply)
	}
	return replies
}

const initialize = `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}`

func TestTheHandshakeListAndACall(t *testing.T) {
	calls := 0
	replies := exchange(t, echoServer(&calls),
		initialize,
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`,
		`{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"word":"hi"}}}`,
		`{"jsonrpc":"2.0","id":4,"method":"ping"}`,
	)
	if len(replies) != 4 {
		t.Fatalf("%d replies, want 4 (a notification is never answered): %v", len(replies), replies)
	}
	init := replies[0]["result"].(map[string]any)
	if init["protocolVersion"] != "2025-06-18" {
		t.Errorf("protocol %v", init["protocolVersion"])
	}
	tools := replies[1]["result"].(map[string]any)["tools"].([]any)
	schema := tools[0].(map[string]any)["inputSchema"].(map[string]any)
	if schema["additionalProperties"] != false {
		t.Errorf("a tool's schema must refuse undeclared arguments: %v", schema)
	}
	result := replies[2]["result"].(map[string]any)
	if result["isError"] != false || result["structuredContent"].(map[string]any)["word"] != "hi" {
		t.Errorf("call result %v", result)
	}
	text := result["content"].([]any)[0].(map[string]any)["text"].(string)
	var decoded map[string]any
	if err := json.Unmarshal([]byte(text), &decoded); err != nil || decoded["word"] != "hi" {
		t.Errorf("the text content is the structured result as JSON, not prose: %q", text)
	}
	if calls != 1 {
		t.Errorf("%d calls", calls)
	}
}

func TestAnUnknownVersionGetsTheNewest(t *testing.T) {
	calls := 0
	replies := exchange(t, echoServer(&calls),
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"1999-01-01"}}`)
	if got := replies[0]["result"].(map[string]any)["protocolVersion"]; got != ProtocolVersions[0] {
		t.Errorf("negotiated %v", got)
	}
}

// An argument the tool did not declare is refused before the handler
// runs — however it is spelled, and whatever it claims to grant.
func TestUndeclaredArgumentsAreRefusedBeforeTheToolRuns(t *testing.T) {
	for _, arguments := range []string{
		`{"word":"hi","grants":{"net.http.outbound":true}}`,
		`{"word":"hi","capabilities":["config.read.values"]}`,
		`{"word":"hi","net.tcp.connect":true}`,
		`{"words":["a"]}`,
		`{"word":3}`,
		`{"word":"hi","words":"a"}`,
		`{"word":"hi","mode":"shout"}`,
	} {
		calls := 0
		replies := exchange(t, echoServer(&calls), initialize,
			`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":`+arguments+`}}`)
		failure, ok := replies[1]["error"].(map[string]any)
		if !ok {
			t.Errorf("%s: accepted: %v", arguments, replies[1])
			continue
		}
		if failure["code"].(float64) != CodeInvalidParams {
			t.Errorf("%s: code %v", arguments, failure["code"])
		}
		if calls != 0 {
			t.Errorf("%s: the tool ran", arguments)
		}
	}
}

func TestProtocolErrors(t *testing.T) {
	calls := 0
	replies := exchange(t, echoServer(&calls),
		`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`,
		`not json`,
		initialize,
		`{"jsonrpc":"2.0","id":3,"method":"resources/list"}`,
		`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"nope"}}`,
	)
	want := []int{CodeInvalidRequest, CodeParseError, 0, CodeMethodNotFound, CodeInvalidParams}
	for index, code := range want {
		failure, _ := replies[index]["error"].(map[string]any)
		switch {
		case code == 0 && failure != nil:
			t.Errorf("reply %d: %v", index, failure)
		case code != 0 && (failure == nil || int(failure["code"].(float64)) != code):
			t.Errorf("reply %d: want code %d, got %v", index, code, replies[index])
		}
	}
	if calls != 0 {
		t.Errorf("%d calls", calls)
	}
}

func TestAToolErrorIsAResultNotAProtocolError(t *testing.T) {
	server := &Server{Name: "culprit", Tools: []Tool{{
		Name: "fails", Input: Schema{Properties: map[string]Property{}},
		Handler: func(context.Context, map[string]any) Result {
			return Result{Structured: map[string]any{"error": "could not run"}, IsError: true}
		},
	}}}
	replies := exchange(t, server, initialize,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"fails","arguments":{}}}`)
	result := replies[1]["result"].(map[string]any)
	if result["isError"] != true || result["structuredContent"].(map[string]any)["error"] != "could not run" {
		t.Errorf("%v", result)
	}
}
