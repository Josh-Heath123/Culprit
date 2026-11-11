// Package mcp is the Model Context Protocol, as `culprit mcp` speaks it
// (Phase 35 part 1): JSON-RPC 2.0, one message per line, on stdin and
// stdout. Nothing else.
//
// This package is the protocol and nothing more. It knows no probe, no
// walk and no grant; it offers the tools it is given, refuses a call whose
// arguments the tool did not declare, and returns what the tool returned.
// It links no network package (D8, amended: `go list ./internal/...`
// covers it the day it exists) and opens no listener: the only transport
// is the pair of streams the process was started with, so a coding agent
// reaches it by starting the binary, and nothing reaches it any other way.
//
// It calls no model. A response is the tool's structured result, and its
// text content is that same result encoded as JSON — never prose.
package mcp

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"
)

// ProtocolVersions are the MCP revisions this server speaks, newest first.
// A client asking for one of them gets it; any other gets the newest, and
// decides for itself whether to go on (the specification's negotiation).
var ProtocolVersions = []string{"2025-06-18", "2025-03-26", "2024-11-05"}

// JSON-RPC error codes.
const (
	CodeParseError     = -32700
	CodeInvalidRequest = -32600
	CodeMethodNotFound = -32601
	CodeInvalidParams  = -32602
	CodeInternalError  = -32603
)

// Annotations are the hints a client may show about a tool. Every Culprit
// tool is read-only: none has a destructive or an idempotency hint to give.
type Annotations struct {
	Title           string `json:"title,omitempty"`
	ReadOnlyHint    bool   `json:"readOnlyHint"`
	DestructiveHint bool   `json:"destructiveHint"`
	OpenWorldHint   bool   `json:"openWorldHint"`
}

// Result is what a tool returns. Structured is the answer; IsError marks a
// call the tool refused or could not complete, its reason in Structured.
type Result struct {
	Structured any
	IsError    bool
}

// Tool is one callable tool. Input is its argument schema, and it is
// enforced, not advisory: a call whose arguments do not satisfy it is
// refused before Handler runs.
type Tool struct {
	Name        string
	Title       string
	Description string
	Input       Schema
	Output      map[string]any
	Annotations Annotations
	Handler     func(ctx context.Context, arguments map[string]any) Result
}

// Server offers tools over one pair of streams.
type Server struct {
	Name         string
	Version      string
	Instructions string
	Tools        []Tool
}

type request struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type response struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  any             `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// maxMessage bounds one line: a request is a tool name and a few
// arguments, never a payload.
const maxMessage = 1 << 20

// Run reads requests from in and writes responses to out until in ends
// or ctx is done. Requests are answered one at a time, in order.
func (s *Server) Run(ctx context.Context, in io.Reader, out io.Writer) error {
	scanner := bufio.NewScanner(in)
	scanner.Buffer(make([]byte, 64*1024), maxMessage)
	encoder := json.NewEncoder(out)
	encoder.SetEscapeHTML(false)
	initialized := false
	for scanner.Scan() {
		if err := ctx.Err(); err != nil {
			return err
		}
		line := bytes.TrimSpace(scanner.Bytes())
		if len(line) == 0 {
			continue
		}
		reply := s.handle(ctx, line, &initialized)
		if reply == nil {
			continue
		}
		if err := encoder.Encode(reply); err != nil {
			return err
		}
	}
	if err := scanner.Err(); err != nil && !errors.Is(err, io.EOF) {
		return fmt.Errorf("reading a request: %w", err)
	}
	return nil
}

func (s *Server) handle(ctx context.Context, line []byte, initialized *bool) *response {
	var message request
	if err := json.Unmarshal(line, &message); err != nil {
		return &response{JSONRPC: "2.0", ID: json.RawMessage("null"),
			Error: &rpcError{CodeParseError, "not a JSON-RPC message: " + err.Error()}}
	}
	notification := len(message.ID) == 0 || string(message.ID) == "null"
	if message.JSONRPC != "2.0" || message.Method == "" {
		if notification {
			return nil
		}
		return failure(message.ID, CodeInvalidRequest, "a request needs jsonrpc \"2.0\" and a method")
	}
	if notification {
		// notifications/initialized, notifications/cancelled and any
		// other: nothing is answered. A request already running is not
		// interrupted; it is answered when it finishes (docs/LIMITS.md).
		return nil
	}

	switch message.Method {
	case "initialize":
		*initialized = true
		return success(message.ID, s.initialize(message.Params))
	case "ping":
		return success(message.ID, map[string]any{})
	}
	if !*initialized {
		return failure(message.ID, CodeInvalidRequest, "initialize first")
	}
	switch message.Method {
	case "tools/list":
		return success(message.ID, map[string]any{"tools": s.list()})
	case "tools/call":
		result, err := s.call(ctx, message.Params)
		if err != nil {
			return failure(message.ID, CodeInvalidParams, err.Error())
		}
		return success(message.ID, result)
	}
	return failure(message.ID, CodeMethodNotFound, "no method "+message.Method+
		" (this server offers tools only: tools/list, tools/call)")
}

func success(id json.RawMessage, result any) *response {
	return &response{JSONRPC: "2.0", ID: id, Result: result}
}

func failure(id json.RawMessage, code int, message string) *response {
	return &response{JSONRPC: "2.0", ID: id, Error: &rpcError{code, message}}
}

func (s *Server) initialize(params json.RawMessage) map[string]any {
	var asked struct {
		ProtocolVersion string `json:"protocolVersion"`
	}
	_ = json.Unmarshal(params, &asked)
	version := ProtocolVersions[0]
	for _, known := range ProtocolVersions {
		if known == asked.ProtocolVersion {
			version = known
		}
	}
	result := map[string]any{
		"protocolVersion": version,
		"capabilities":    map[string]any{"tools": map[string]any{"listChanged": false}},
		"serverInfo":      map[string]any{"name": s.Name, "version": s.Version},
	}
	if s.Instructions != "" {
		result["instructions"] = s.Instructions
	}
	return result
}

func (s *Server) list() []map[string]any {
	tools := make([]map[string]any, 0, len(s.Tools))
	for _, tool := range s.Tools {
		entry := map[string]any{
			"name":        tool.Name,
			"description": tool.Description,
			"inputSchema": tool.Input.JSON(),
			"annotations": tool.Annotations,
		}
		if tool.Title != "" {
			entry["title"] = tool.Title
		}
		if tool.Output != nil {
			entry["outputSchema"] = tool.Output
		}
		tools = append(tools, entry)
	}
	return tools
}

func (s *Server) call(ctx context.Context, params json.RawMessage) (map[string]any, error) {
	var asked struct {
		Name      string         `json:"name"`
		Arguments map[string]any `json:"arguments"`
	}
	decoder := json.NewDecoder(bytes.NewReader(params))
	decoder.UseNumber()
	if err := decoder.Decode(&asked); err != nil {
		return nil, fmt.Errorf("tools/call params: %w", err)
	}
	var tool *Tool
	for index := range s.Tools {
		if s.Tools[index].Name == asked.Name {
			tool = &s.Tools[index]
		}
	}
	if tool == nil {
		return nil, fmt.Errorf("no tool %q; tools/list names them", asked.Name)
	}
	if asked.Arguments == nil {
		asked.Arguments = map[string]any{}
	}
	// Before the handler, always: an argument the tool did not declare —
	// a grant, a capability, anything — is refused here, so no tool can be
	// handed authority by its caller.
	if err := tool.Input.Check(asked.Arguments); err != nil {
		return nil, fmt.Errorf("%s: %w", tool.Name, err)
	}
	result := tool.Handler(ctx, asked.Arguments)
	return Encode(result)
}

// Encode is a result as tools/call returns it: the structured answer, and
// the same answer as JSON text for a client that reads content only.
func Encode(result Result) (map[string]any, error) {
	var text bytes.Buffer
	encoder := json.NewEncoder(&text)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(result.Structured); err != nil {
		return nil, fmt.Errorf("encoding the result: %w", err)
	}
	return map[string]any{
		"content":           []map[string]any{{"type": "text", "text": strings.TrimSuffix(text.String(), "\n")}},
		"structuredContent": json.RawMessage(bytes.TrimSpace(text.Bytes())),
		"isError":           result.IsError,
	}, nil
}

// ---- argument schemas ---------------------------------------------------------

// Type is a JSON type an argument may take.
type Type string

const (
	String  Type = "string"
	Strings Type = "array of strings"
	Object  Type = "object"
	Boolean Type = "boolean"
)

// Property is one argument.
type Property struct {
	Type        Type
	Description string
	// Enum, when set, is every value a String may take.
	Enum []string
}

// Schema is a tool's arguments: an object with these properties, these
// required, and nothing else. additionalProperties is always false.
type Schema struct {
	Properties map[string]Property
	Required   []string
}

// JSON is the schema as tools/list publishes it.
func (s Schema) JSON() map[string]any {
	properties := map[string]any{}
	for name, property := range s.Properties {
		entry := map[string]any{"description": property.Description}
		switch property.Type {
		case Strings:
			entry["type"] = "array"
			entry["items"] = map[string]any{"type": "string"}
		default:
			entry["type"] = string(property.Type)
		}
		if len(property.Enum) > 0 {
			entry["enum"] = property.Enum
		}
		properties[name] = entry
	}
	schema := map[string]any{
		"type":                 "object",
		"properties":           properties,
		"additionalProperties": false,
	}
	if len(s.Required) > 0 {
		schema["required"] = s.Required
	}
	return schema
}

// Check refuses arguments that do not satisfy the schema: an undeclared
// name, a missing required one, or a value of the wrong type.
func (s Schema) Check(arguments map[string]any) error {
	var unknown []string
	for name := range arguments {
		if _, declared := s.Properties[name]; !declared {
			unknown = append(unknown, name)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return fmt.Errorf("refused: %s %s not an argument of this tool. Grants are the environment's, "+
			"in culprit.yaml; no argument can add one", strings.Join(unknown, ", "), plural(len(unknown), "is", "are"))
	}
	for _, name := range s.Required {
		if _, given := arguments[name]; !given {
			return fmt.Errorf("%s is required", name)
		}
	}
	names := make([]string, 0, len(arguments))
	for name := range arguments {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		if err := s.Properties[name].check(name, arguments[name]); err != nil {
			return err
		}
	}
	return nil
}

func (p Property) check(name string, value any) error {
	switch p.Type {
	case String:
		text, ok := value.(string)
		if !ok {
			return fmt.Errorf("%s must be a string", name)
		}
		if len(p.Enum) > 0 {
			for _, allowed := range p.Enum {
				if text == allowed {
					return nil
				}
			}
			return fmt.Errorf("%s must be one of %s", name, strings.Join(p.Enum, ", "))
		}
	case Strings:
		items, ok := value.([]any)
		if !ok {
			return fmt.Errorf("%s must be an array of strings", name)
		}
		for _, item := range items {
			if _, ok := item.(string); !ok {
				return fmt.Errorf("%s must be an array of strings", name)
			}
		}
	case Object:
		if _, ok := value.(map[string]any); !ok {
			return fmt.Errorf("%s must be an object", name)
		}
	case Boolean:
		if _, ok := value.(bool); !ok {
			return fmt.Errorf("%s must be true or false", name)
		}
	}
	return nil
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// Text reads a string argument, "" when absent.
func Text(arguments map[string]any, name string) string {
	text, _ := arguments[name].(string)
	return text
}

// List reads an array-of-strings argument.
func List(arguments map[string]any, name string) []string {
	items, _ := arguments[name].([]any)
	list := make([]string, 0, len(items))
	for _, item := range items {
		if text, ok := item.(string); ok {
			list = append(list, text)
		}
	}
	return list
}

// Flag reads a boolean argument, false when absent.
func Flag(arguments map[string]any, name string) bool {
	flag, _ := arguments[name].(bool)
	return flag
}
