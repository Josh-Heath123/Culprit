// Thin fetch + JSON + error-shaping wrapper only — retries, caching, and
// background refetch are all TanStack Query's job (see src/hooks/), not
// reimplemented here.

import { getToken, setToken } from "@/lib/auth";
import type {
  AgentList,
  Allowance,
  ComponentCreate,
  ComponentCreateResponse,
  ComponentOut,
  ComponentPatch,
  ComponentsOut,
  ConnectionCreate,
  ConnectionOut,
  ConnectionPatch,
  ConnectionsOut,
  GraphOut,
  IncidentDetail,
  InvestigationList,
  InvestigationTree,
  NarrationView,
  KeyCreateResponse,
  LoginResponse,
  PaginatedIncidents,
  PairingCodeCreated,
  PaginatedPostmortems,
  PostmortemCreate,
  PostmortemOut,
  PostmortemPatch,
  TaskCreate,
  TaskCreated,
  TaskView,
  VerificationList,
  TopologyEdgeRef,
  TopologySuggestionsOut,
  UserOut,
  UsersOut,
} from "@/lib/types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  { unauthorizedEndsSession = true }: { unauthorizedEndsSession?: boolean } = {},
): Promise<T> {
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (response.status === 401 && unauthorizedEndsSession) {
    // Session token missing/expired/rejected — drop it so App.tsx's
    // useAuthToken() falls back to the login screen. The ApiError below
    // still throws for this in-flight request, but the component tree
    // that issued it is about to unmount anyway.
    setToken(null);
  }
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body || response.statusText, response.status);
  }
  if (response.status === 204 || response.status === 202) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function login(username: string, password: string): Promise<void> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body || response.statusText, response.status);
  }
  const data = (await response.json()) as LoginResponse;
  setToken(data.access_token);
}

/** logout() only ever needs to clear the local token — there's no
 * server-side session/refresh-token store to revoke (short-lived JWTs,
 * see lib/auth.ts's own comment on why a refresh already means logging
 * in again). */
export function logout(): void {
  setToken(null);
}

// Phase 16: multi-user auth.
export function fetchCurrentUser(): Promise<UserOut> {
  return request<UserOut>("/auth/me");
}

export function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  // A 401 here means the *current password* was wrong, not that the
  // session is — so it is shown in the dialog instead of logging you out
  // (Phase 31.2 truth pass: one typo used to end the session).
  return request<void>(
    "/auth/change-password",
    {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    },
    { unauthorizedEndsSession: false },
  );
}

export function fetchUsers(): Promise<UsersOut> {
  return request<UsersOut>("/users");
}

export function createUser(username: string, password: string, role: string): Promise<UserOut> {
  return request<UserOut>("/users", {
    method: "POST",
    body: JSON.stringify({ username, password, role }),
  });
}

export function patchUser(
  id: string,
  body: { role?: string; disabled?: boolean },
): Promise<UserOut> {
  return request<UserOut>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function resetUserPassword(id: string, newPassword: string): Promise<void> {
  return request<void>(`/users/${id}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ new_password: newPassword }),
  });
}

/** Soft delete (disabled_at) — same semantics as deleteComponent, never
 * deletes the row (api/app/auth/users_router.py::delete_user_endpoint). */
export function deleteUser(id: string): Promise<void> {
  return request<void>(`/users/${id}`, { method: "DELETE" });
}

export function fetchIncidents(limit: number, offset: number): Promise<PaginatedIncidents> {
  return request<PaginatedIncidents>(`/incidents?limit=${limit}&offset=${offset}`);
}

export function fetchIncident(id: string): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/incidents/${id}`);
}

// Phase 32 part 2: investigations. Read-only here — they are written by
// `culprit diagnose` with the project token, never from the dashboard,
// and nothing on this side can open one (field 17: no agent until 33).
export function fetchInvestigations(limit: number): Promise<InvestigationList> {
  return request<InvestigationList>(`/investigations?limit=${limit}`);
}

export function fetchInvestigationTree(id: string): Promise<InvestigationTree> {
  return request<InvestigationTree>(`/investigations/${encodeURIComponent(id)}/tree`);
}

// Phase 27: the system model. Every endpoint here is under
// require_admin (api/app/main.py) — a member's token gets 403, reads
// included. Phase 30 removed the /services alias these replaced; the
// ingest-key and topology-suggestion calls below moved under /model with
// it.
export function fetchComponents(): Promise<ComponentsOut> {
  return request<ComponentsOut>("/model/components");
}

/** Creates a component and issues its first ingest key — returned once,
 * here, and never retrievable again. */
export function createComponent(body: ComponentCreate): Promise<ComponentCreateResponse> {
  return request<ComponentCreateResponse>("/model/components", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchComponent(id: string, body: ComponentPatch): Promise<ComponentOut> {
  return request<ComponentOut>(`/model/components/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** Soft delete (default) or, with `purge`, a hard delete of the
 * component + its keys and connections — never of telemetry history
 * either way (see api/app/model/service.py::delete_component). */
export function deleteComponent(id: string, purge = false): Promise<void> {
  return request<void>(`/model/components/${id}${purge ? "?purge=true" : ""}`, {
    method: "DELETE",
  });
}

export function createKey(componentId: string, label: string | null): Promise<KeyCreateResponse> {
  return request<KeyCreateResponse>(`/model/components/${componentId}/keys`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function revokeKey(componentId: string, keyId: string): Promise<void> {
  return request<void>(`/model/components/${componentId}/keys/${keyId}`, { method: "DELETE" });
}

// Phase 19: topology inference — suggestions only, never applied
// automatically; accept/dismiss are the only things that change what
// correlation actually does (api/app/registry/service.py).
export function fetchTopologySuggestions(): Promise<TopologySuggestionsOut> {
  return request<TopologySuggestionsOut>("/model/topology/suggestions");
}

export function acceptTopologySuggestion(edge: TopologyEdgeRef): Promise<void> {
  return request<void>("/model/topology/suggestions/accept", {
    method: "POST",
    body: JSON.stringify(edge),
  });
}

export function dismissTopologySuggestion(edge: TopologyEdgeRef): Promise<void> {
  return request<void>("/model/topology/suggestions/dismiss", {
    method: "POST",
    body: JSON.stringify(edge),
  });
}

export function fetchConnections(): Promise<ConnectionsOut> {
  return request<ConnectionsOut>("/model/connections");
}

export function createConnection(body: ConnectionCreate): Promise<ConnectionOut> {
  return request<ConnectionOut>("/model/connections", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchConnection(id: string, body: ConnectionPatch): Promise<ConnectionOut> {
  return request<ConnectionOut>(`/model/connections/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteConnection(id: string): Promise<void> {
  return request<void>(`/model/connections/${id}`, { method: "DELETE" });
}

/** `symptom` asks for the ordered set of upstream connections on that
 * component's request path, nearest hop first (Phase 27 acceptance
 * criterion 4). Omit it for the plain graph. */
export function fetchGraph(symptom?: string): Promise<GraphOut> {
  const query = symptom ? `?symptom=${encodeURIComponent(symptom)}` : "";
  return request<GraphOut>(`/model/graph${query}`);
}

// Phase 18: postmortem write path.
export function fetchPostmortems(limit: number, offset: number): Promise<PaginatedPostmortems> {
  return request<PaginatedPostmortems>(`/postmortems?limit=${limit}&offset=${offset}`);
}

export function fetchPostmortem(id: string): Promise<PostmortemOut> {
  return request<PostmortemOut>(`/postmortems/${id}`);
}

export function createPostmortem(body: PostmortemCreate): Promise<PostmortemOut> {
  return request<PostmortemOut>("/postmortems", { method: "POST", body: JSON.stringify(body) });
}

export function patchPostmortem(id: string, body: PostmortemPatch): Promise<PostmortemOut> {
  return request<PostmortemOut>(`/postmortems/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** Sends an empty patch — that's how a "retry" re-enqueues embedding on a
 * failed postmortem without changing any content (see
 * api/app/postmortems/service.py::patch_postmortem). */
export function retryPostmortemEmbedding(id: string): Promise<PostmortemOut> {
  return patchPostmortem(id, {});
}

export function deletePostmortem(id: string): Promise<void> {
  return request<void>(`/postmortems/${id}`, { method: "DELETE" });
}

// Phase 33 part 3: agents. Every route here is an admin's.
export function fetchAgents(): Promise<AgentList> {
  return request<AgentList>("/agents");
}

/** A single-use code, shown once: only its hash is stored. */
export function createPairingCode(): Promise<PairingCodeCreated> {
  return request<PairingCodeCreated>("/agents/pairing-codes", { method: "POST" });
}

/** Narrow only: the API refuses a grant the agent does not report. */
export function setAllowance(agentId: string, environment: string, grants: string[]): Promise<Allowance> {
  return request<Allowance>(`/agents/${encodeURIComponent(agentId)}/grants`, {
    method: "PATCH",
    body: JSON.stringify({ environment, grants }),
  });
}

export function revokeAgent(agentId: string): Promise<void> {
  return request<void>(`/agents/${encodeURIComponent(agentId)}/revoke`, { method: "POST" });
}

export function createTask(agentId: string, body: TaskCreate): Promise<TaskCreated> {
  return request<TaskCreated>(`/agents/${encodeURIComponent(agentId)}/tasks`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Phase 35 part 2: an investigation's narration — off, not narrated yet,
// complete, failed or refused. The API re-checks prose before it serves it.
export function fetchNarration(investigationId: string): Promise<NarrationView> {
  return request<NarrationView>(`/investigations/${encodeURIComponent(investigationId)}/narration`);
}

// Phase 34 part 2: an investigation's verifications, newest first.
export function fetchVerifications(investigationId: string): Promise<VerificationList> {
  return request<VerificationList>(`/investigations/${encodeURIComponent(investigationId)}/verifications`);
}

export function fetchTask(agentId: string, taskId: string): Promise<TaskView> {
  return request<TaskView>(`/agents/${encodeURIComponent(agentId)}/tasks/${encodeURIComponent(taskId)}`);
}
