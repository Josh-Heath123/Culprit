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

// Source is agent.Source over the control plane.
type Source struct {
	Client *Client
	// Audit is the agent's local log; each result is preceded by shipping
	// every entry the control plane does not yet hold.
	Audit *agent.AuditLog
	// shipped is the control plane's head, once known.
	shipped   int64
	headKnown bool
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
	if len(result.Readings) > 0 {
		response, err := s.Client.send(ctx, http.MethodPost, "/readings",
			map[string]any{"readings": result.Readings}, true)
		if err != nil {
			return err
		}
		if err := expect(response, "/readings", http.StatusCreated); err != nil {
			return err
		}
	}
	investigation := ""
	if result.Investigation != nil {
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
		response, err := s.Client.send(ctx, http.MethodPost, path, map[string]any{
			"source": incoming.Task.Verify.Source, "verification": result.Verification,
		}, true)
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
// in order. The control plane refuses anything that does not extend its
// stored chain; on that refusal the head is read again, once.
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
		if len(lines) == 0 {
			return nil
		}
		for start := 0; start < len(lines); start += 500 {
			end := min(start+500, len(lines))
			response, err := s.Client.send(ctx, http.MethodPost, "/agents/me/audit",
				map[string]any{"entries": lines[start:end]}, true)
			if err != nil {
				return err
			}
			if response.Status == http.StatusConflict {
				s.headKnown = false
				break
			}
			if err := expect(response, "/agents/me/audit", http.StatusOK); err != nil {
				return err
			}
			s.shipped = s.shipped + int64(end-start)
		}
		if s.headKnown && s.shipped == last {
			return nil
		}
	}
	return fmt.Errorf("the control plane's audit chain and this agent's do not agree; " +
		"compare them with `culprit agent verify` before going on")
}
