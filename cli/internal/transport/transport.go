// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

// Package transport is how a paired agent talks to the control plane
// (docs/DIAGNOSTIC_PLAN.md Phase 33 part 2): it claims tasks, reports
// results, posts readings and investigations, and ships the agent's audit
// chain — every request signed with the agent's own Ed25519 key
// (internal/agentauth), over the one address the agent's configuration
// names.
//
// It is the third package the D8 allowlist lets reach the network
// (TestTheNetworkBoundaryIsAnAllowlist), and it is built so it cannot reach
// anywhere else:
//
//   - its dialer refuses any address but the configured host and port,
//     whatever a URL, a redirect or a DNS answer says;
//   - it ignores HTTP_PROXY and friends, which would make it dial a proxy;
//   - it follows no redirect: a 3xx is an error, not a new destination;
//   - it opens no listener. Outbound only: nothing in the user's network
//     has to accept a connection for the agent to work.
//
// It decides nothing. What a task may do is the agent's decision
// (internal/agent), taken before anything here is asked to send a byte.
package transport

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/agent"
	"github.com/josh-heath123/culprit/cli/internal/agentauth"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// ErrRedirect is what a 3xx becomes.
var ErrRedirect = errors.New("the control plane answered with a redirect, which this agent does not follow")

// Client is one agent's connection to its control plane.
type Client struct {
	base    *url.URL
	address string // host:port, the only one the dialer allows
	http    *http.Client
	agentID string
	key     ed25519.PrivateKey
	Now     func() time.Time
}

// New builds a client for the API root at base (control_plane.url).
func New(base, agentID string, key ed25519.PrivateKey, timeout time.Duration) (*Client, error) {
	parsed, err := url.Parse(base)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return nil, fmt.Errorf("the control plane URL %q is not an http or https URL with a host", base)
	}
	port := parsed.Port()
	if port == "" {
		port = map[string]string{"http": "80", "https": "443"}[parsed.Scheme]
	}
	address := net.JoinHostPort(parsed.Hostname(), port)
	client := &Client{base: parsed, address: address, agentID: agentID, key: key, Now: time.Now}

	dialer := &net.Dialer{Timeout: timeout}
	transport := &http.Transport{
		Proxy: nil, // never a proxy from the environment
		DialContext: func(ctx context.Context, network, target string) (net.Conn, error) {
			if target != address {
				return nil, fmt.Errorf("refusing to dial %s: this agent reaches only its control plane, %s", target, address)
			}
			return dialer.DialContext(ctx, network, target)
		},
		ForceAttemptHTTP2:     true,
		TLSHandshakeTimeout:   timeout,
		ResponseHeaderTimeout: timeout,
		MaxIdleConns:          2,
		IdleConnTimeout:       30 * time.Second,
	}
	client.http = &http.Client{
		Transport: transport,
		Timeout:   4 * timeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return ErrRedirect
		},
	}
	return client, nil
}

// Address is the host:port the client is confined to.
func (c *Client) Address() string { return c.address }

func (c *Client) endpoint(path string) string {
	return strings.TrimRight(c.base.String(), "/") + path
}

// Response is a status and a body, read whole.
type Response struct {
	Status int
	Body   []byte
}

// send makes one request. Signed requests carry the four agentauth
// headers over the path relative to the API root.
func (c *Client) send(ctx context.Context, method, path string, payload any, signed bool) (Response, error) {
	var body []byte
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return Response{}, err
		}
		body = encoded
	}
	request, err := http.NewRequestWithContext(ctx, method, c.endpoint(path), bytes.NewReader(body))
	if err != nil {
		return Response{}, err
	}
	if payload != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	if signed {
		nonce, err := agentauth.NewNonce()
		if err != nil {
			return Response{}, err
		}
		for name, value := range agentauth.Headers(c.key, agentauth.Request{
			Method: method, Path: path, Body: body,
			Timestamp: c.Now().Unix(), Nonce: nonce, AgentID: c.agentID,
		}) {
			request.Header.Set(name, value)
		}
	}
	response, err := c.http.Do(request)
	if err != nil {
		return Response{}, fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer response.Body.Close()
	read, err := io.ReadAll(io.LimitReader(response.Body, 16<<20))
	if err != nil {
		return Response{}, fmt.Errorf("%s %s: the answer could not be read", method, path)
	}
	return Response{Status: response.StatusCode, Body: read}, nil
}

func expect(response Response, path string, statuses ...int) error {
	for _, status := range statuses {
		if response.Status == status {
			return nil
		}
	}
	detail := strings.TrimSpace(string(response.Body))
	if len(detail) > 300 {
		detail = detail[:300]
	}
	return fmt.Errorf("%s: the control plane answered %d: %s", path, response.Status, detail)
}

// ---- pairing --------------------------------------------------------------------------

// Registration is what `culprit agent pair` sends: the code, the agent's
// id, the public half of its key, and what its configuration grants. The
// private key is not a field, so it cannot be sent.
type Registration struct {
	PairingCode string              `json:"pairing_code"`
	AgentID     string              `json:"agent_id"`
	PublicKey   string              `json:"public_key"`
	Grants      map[string][]string `json:"grants"`
}

// NewRegistration builds a registration from the agent's key.
func NewRegistration(code, agentID string, key ed25519.PrivateKey, grants map[string][]string) Registration {
	public := key.Public().(ed25519.PublicKey)
	return Registration{PairingCode: code, AgentID: agentID,
		PublicKey: base64.StdEncoding.EncodeToString(public), Grants: grants}
}

// Register pairs the agent. Unsigned: the single-use code is the credential.
func (c *Client) Register(ctx context.Context, registration Registration) error {
	response, err := c.send(ctx, http.MethodPost, "/agents/register", registration, false)
	if err != nil {
		return err
	}
	return expect(response, "/agents/register", http.StatusCreated)
}

// ---- keys -----------------------------------------------------------------------------

const keyHeader = "culprit-agent-key-v1"

// GenerateKey makes a new Ed25519 key and its file form.
func GenerateKey() (ed25519.PrivateKey, []byte, error) {
	_, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, nil, err
	}
	encoded := keyHeader + "\n" + base64.StdEncoding.EncodeToString(private.Seed()) + "\n"
	return private, []byte(encoded), nil
}

// ParseKey reads a key file's contents.
func ParseKey(data []byte) (ed25519.PrivateKey, error) {
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) != 2 || strings.TrimSpace(lines[0]) != keyHeader {
		return nil, fmt.Errorf("not a culprit agent key file")
	}
	seed, err := base64.StdEncoding.DecodeString(strings.TrimSpace(lines[1]))
	if err != nil || len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf("not a culprit agent key file")
	}
	return ed25519.NewKeyFromSeed(seed), nil
}

// ---- the agent's task source ----------------------------------------------------------

// claimed is a task as the control plane hands it over.
type claimed struct {
	ID          string              `json:"id"`
	Environment string              `json:"environment"`
	Kind        string              `json:"kind"`
	Probe       *agent.ProbeTask    `json:"probe,omitempty"`
	Diagnose    *agent.DiagnoseTask `json:"diagnose,omitempty"`
	Verify      *agent.VerifyTask   `json:"verify,omitempty"`
	Allowance   []string            `json:"allowance"`
}

// BulkBodyBytes is the control plane's default cap on a body posted to
// one of its bulk routes, the only routes this agent posts batches to:
// readings, investigations, verifications, results and its audit chain
// (api/app/body_limits.py, F44-043). If CULPRIT_MAX_BULK_BODY_BYTES on the
// control plane is set lower, its 413 says so and the batch shrinks.
const BulkBodyBytes = 16 << 20

// maxAuditEntries is POST /agents/me/audit's own limit on entries.
const maxAuditEntries = 1000

// Source is agent.Source over the control plane.
type Source struct {
	Client *Client
	// Audit is the agent's local log; each result is preceded by shipping
	// every entry the control plane does not yet hold.
	Audit *agent.AuditLog
	// BodyBytes is the cap this agent assumes on a bulk route; 0 is
	// BulkBodyBytes. Batches are sized under half of it, by bytes.
	BodyBytes int
	// Logf is the agent's own log; nil logs nothing.
	Logf func(format string, args ...any)
	// shipped is the control plane's head, once known.
	shipped   int64
	headKnown bool
	// budget is the batch size in bytes, under half the cap; a 413 lowers
	// it for every later batch, so a refused batch is never sent again.
	budget int
	// held is the seq of an audit entry that alone is over the cap: kept
	// in the local log and never sent, so nothing after it can be either
	// (the chain is in order). 0 is none.
	held int64
}

func (s *Source) capBytes() int {
	if s.BodyBytes > 0 {
		return s.BodyBytes
	}
	return BulkBodyBytes
}

func (s *Source) batchBudget() int {
	if s.budget <= 0 || s.budget > s.capBytes()/2 {
		s.budget = s.capBytes() / 2
	}
	return s.budget
}

func (s *Source) logf(format string, args ...any) {
	if s.Logf != nil {
		s.Logf(format, args...)
	}
}

// TooLarge is a body this agent will not send, or the control plane
// refused, for its size. It is never sent again unchanged.
type TooLarge struct {
	What  string
	Bytes int
	Limit int
}

func (e *TooLarge) Error() string {
	return fmt.Sprintf("%s is %d bytes, %s; it is not sent again "+
		"(CULPRIT_MAX_BULK_BODY_BYTES on the control plane raises the limit)",
		e.What, e.Bytes, overWhat(e.Limit))
}

// overWhat says what a body was over: the cap this agent knows, or, when
// the control plane refused it alone (413), the control plane's own.
func overWhat(limit int) string {
	if limit > 0 {
		return fmt.Sprintf("over the control plane's limit of %d bytes for it", limit)
	}
	return "and the control plane refused it alone as too large (413)"
}

// encodedLen is the bytes value adds to a JSON array: itself, encoded,
// and a comma.
func encodedLen(value any) int {
	encoded, err := json.Marshal(value)
	if err != nil {
		return 0
	}
	return len(encoded) + 1
}

// firstBatch is how many of items, from the first, fit one request: a
// JSON array wrapped in an object of overhead bytes, within budget, and at
// most most items. One item always goes alone if it fits limit; an item
// that alone is over limit gives 0.
func firstBatch(items []any, overhead, budget, limit, most int) (count int, size int) {
	total := overhead
	for index, item := range items {
		length := encodedLen(item)
		if index == 0 && overhead+length > limit {
			return 0, overhead + length
		}
		if index > 0 && (total+length > budget || index == most) {
			return index, total
		}
		total += length
	}
	return len(items), total
}

// Next claims the agent's oldest waiting task, or returns nil.
func (s *Source) Next(ctx context.Context) (*agent.Incoming, error) {
	response, err := s.Client.send(ctx, http.MethodPost, "/agents/me/tasks/claim", nil, true)
	if err != nil {
		return nil, err
	}
	if response.Status == http.StatusNoContent {
		return nil, nil
	}
	if err := expect(response, "/agents/me/tasks/claim", http.StatusOK); err != nil {
		return nil, err
	}
	var task claimed
	if err := json.Unmarshal(response.Body, &task); err != nil {
		return nil, fmt.Errorf("the claimed task is not one this agent can read")
	}
	allowance := task.Allowance
	if allowance == nil {
		// Present always; an empty allowance narrows to nothing.
		allowance = []string{}
	}
	return &agent.Incoming{
		Handle: task.ID,
		Task: agent.Task{
			ID: task.ID, Environment: task.Environment, Kind: task.Kind,
			Probe: task.Probe, Diagnose: task.Diagnose, Verify: task.Verify, Allowance: allowance,
		},
	}, nil
}

type resultSummary struct {
	Outcome          string   `json:"outcome"`
	Reason           string   `json:"reason,omitempty"`
	GrantsHeld       []string `json:"grants_held"`
	AllowanceIgnored []string `json:"allowance_ignored"`
	Readings         int      `json:"readings"`
	InvestigationID  string   `json:"investigation_id,omitempty"`
	VerificationID   string   `json:"verification_id,omitempty"`
	Verdict          string   `json:"verdict,omitempty"`
}

// Complete ships the audit chain, then what the task measured, then its
// result: by the time the control plane hears how a task ended, it holds
// the record of every probe that task ran.
func (s *Source) Complete(ctx context.Context, incoming *agent.Incoming, result agent.Result) error {
	if err := s.ShipAudit(ctx); err != nil {
		return err
	}
	if err := s.shipReadings(ctx, result.Readings); err != nil {
		return err
	}
	investigation := ""
	if result.Investigation != nil {
		if err := s.fits("the investigation "+result.Investigation.ID, result.Investigation); err != nil {
			return err
		}
		response, err := s.Client.send(ctx, http.MethodPost, "/investigations", result.Investigation, true)
		if err != nil {
			return err
		}
		if err := expect(response, "/investigations", http.StatusCreated, http.StatusConflict); err != nil {
			return err
		}
		investigation = result.Investigation.ID
	}
	verification := ""
	if result.Verification != nil && incoming.Task.Verify != nil {
		// The verification, before the result that names it: by the time
		// the control plane hears the task ended, it holds what it measured.
		path := "/investigations/" + url.PathEscape(result.Verification.InvestigationID) + "/verifications"
		body := map[string]any{"source": incoming.Task.Verify.Source, "verification": result.Verification}
		if err := s.fits("the verification "+result.Verification.ID, body); err != nil {
			return err
		}
		response, err := s.Client.send(ctx, http.MethodPost, path, body, true)
		if err != nil {
			return err
		}
		if err := expect(response, path, http.StatusCreated, http.StatusConflict); err != nil {
			return err
		}
		verification = result.Verification.ID
	}
	readings := len(result.Readings)
	if result.Investigation != nil {
		readings = len(result.Investigation.Readings)
	}
	if result.Verification != nil {
		readings = len(result.Verification.Reran)
	}
	summary := resultSummary{
		Outcome: result.Outcome, Reason: truncate(result.Reason, 4000),
		GrantsHeld: nonNil(result.GrantsHeld), AllowanceIgnored: nonNil(result.AllowanceIgnored),
		Readings: readings, InvestigationID: investigation,
		VerificationID: verification, Verdict: string(result.Verdict),
	}
	path := "/agents/me/tasks/" + url.PathEscape(incoming.Handle) + "/result"
	response, err := s.Client.send(ctx, http.MethodPost, path, summary, true)
	if err != nil {
		return err
	}
	return expect(response, path, http.StatusNoContent)
}

// fits refuses, before sending, one document over the cap: it cannot be
// split, and a 413 is never met by sending the same body again.
func (s *Source) fits(what string, payload any) error {
	if size := encodedLen(payload) - 1; size > s.capBytes() {
		return &TooLarge{What: what, Bytes: size, Limit: s.capBytes()}
	}
	return nil
}

// shipReadings posts a task's readings in batches sized by bytes, under
// half the cap (F44-043). A 413 halves the batch and sends a smaller one,
// never the same one again; one reading over the cap, or refused alone,
// is an error and is not sent again.
func (s *Source) shipReadings(ctx context.Context, readings []model.Reading) error {
	items := make([]any, len(readings))
	for index := range readings {
		items[index] = readings[index]
	}
	const overhead = len(`{"readings":[]}`)
	for start := 0; start < len(items); {
		count, size := firstBatch(items[start:], overhead, s.batchBudget(), s.capBytes(), len(items))
		what := fmt.Sprintf("reading %d of %d", start+1, len(items))
		if count == 0 {
			return &TooLarge{What: what, Bytes: size, Limit: s.capBytes()}
		}
		response, err := s.Client.send(ctx, http.MethodPost, "/readings",
			map[string]any{"readings": readings[start : start+count]}, true)
		if err != nil {
			return err
		}
		if response.Status == http.StatusRequestEntityTooLarge {
			if count == 1 {
				return &TooLarge{What: what, Bytes: size}
			}
			s.budget = size / 2
			continue
		}
		if err := expect(response, "/readings", http.StatusCreated); err != nil {
			return err
		}
		start += count
	}
	return nil
}

func nonNil(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

func truncate(text string, limit int) string {
	if len(text) <= limit {
		return text
	}
	return text[:limit]
}

type head struct {
	Seq  int64  `json:"seq"`
	Hash string `json:"hash"`
}

// ShipAudit sends every local entry the control plane does not hold yet,
// in order, in batches sized by bytes under half the cap (F44-043, as Q49
// ruled), never by entry count alone. The control plane refuses anything
// that does not extend its stored chain; on that refusal the head is read
// again, once.
//
// A 413 is never met with the same request: the batch is halved and the
// smaller one sent. An entry that alone is over the cap, found here or by
// a 413 on it alone, is held: kept in the local log, logged with its
// reason, and never sent. The chain is in order, so nothing after it is
// sent either; the agent carries on with its tasks, and `culprit agent
// verify` shows where the control plane's copy stops.
func (s *Source) ShipAudit(ctx context.Context) error {
	if s.Audit == nil {
		return nil
	}
	for attempt := 0; attempt < 2; attempt++ {
		if !s.headKnown {
			response, err := s.Client.send(ctx, http.MethodGet, "/agents/me/audit/head", nil, true)
			if err != nil {
				return err
			}
			if err := expect(response, "/agents/me/audit/head", http.StatusOK); err != nil {
				return err
			}
			var known head
			if err := json.Unmarshal(response.Body, &known); err != nil {
				return fmt.Errorf("the control plane's audit head is not readable")
			}
			s.shipped, s.headKnown = known.Seq, true
		}
		lines, last, err := s.Audit.LinesAfter(s.shipped)
		if err != nil {
			return err
		}
		if s.held > s.shipped {
			// Only what comes before the held entry can be shipped.
			lines = lines[:min(len(lines), int(s.held-s.shipped-1))]
			last = s.held - 1
		}
		items := make([]any, len(lines))
		for index, line := range lines {
			items[index] = line
		}
		const overhead = len(`{"entries":[]}`)
		conflict := false
		for start := 0; start < len(lines); {
			count, size := firstBatch(items[start:], overhead, s.batchBudget(), s.capBytes(), maxAuditEntries)
			if count == 0 {
				s.hold(s.shipped+1, size, s.capBytes())
				return nil
			}
			response, err := s.Client.send(ctx, http.MethodPost, "/agents/me/audit",
				map[string]any{"entries": lines[start : start+count]}, true)
			if err != nil {
				return err
			}
			if response.Status == http.StatusRequestEntityTooLarge {
				if count == 1 {
					s.hold(s.shipped+1, size, 0)
					return nil
				}
				s.budget = size / 2
				continue
			}
			if response.Status == http.StatusConflict {
				s.headKnown, conflict = false, true
				break
			}
			if err := expect(response, "/agents/me/audit", http.StatusOK); err != nil {
				return err
			}
			s.shipped += int64(count)
			start += count
		}
		if !conflict && s.shipped == last {
			return nil
		}
	}
	return fmt.Errorf("the control plane's audit chain and this agent's do not agree; " +
		"compare them with `culprit agent verify` before going on")
}

// hold records the audit entry at seq as one this agent keeps and never
// sends, and says why in its log, once.
func (s *Source) hold(seq int64, size, limit int) {
	if s.held == seq {
		return
	}
	s.held = seq
	s.logf("audit entry %d is %d bytes, %s: kept in the local audit log and not sent; "+
		"the entries after it are not shipped "+
		"(CULPRIT_MAX_BULK_BODY_BYTES on the control plane raises the limit)", seq, size, overWhat(limit))
}
