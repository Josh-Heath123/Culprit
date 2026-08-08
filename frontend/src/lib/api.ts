// Thin fetch + JSON + error-shaping wrapper only — retries, caching, and
// background refetch are all TanStack Query's job (see src/hooks/), not
// reimplemented here.

import { getToken, setToken } from "@/lib/auth";
import type {
  IncidentDetail,
  KeyCreateResponse,
  LoginResponse,
  PaginatedIncidents,
  PaginatedPostmortems,
  PostmortemCreate,
  PostmortemOut,
  PostmortemPatch,
  ServiceCreate,
  ServiceCreateResponse,
  ServiceOut,
  ServicePatch,
  ServicesOut,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (response.status === 401) {
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
  return request<void>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
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

/** Soft delete (disabled_at) — same semantics as deleteService, never
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

export function regenerateRootCause(id: string): Promise<{ status: string; incident_id: string }> {
  return request(`/incidents/${id}/regenerate-root-cause`, { method: "POST" });
}

// Phase 14 (registry) — Phase 16 moved every /services endpoint,
// including GET, onto require_admin (api/app/main.py) — a member's
// token gets 403 here now, not just from writes.
export function fetchServices(): Promise<ServicesOut> {
  return request<ServicesOut>("/services");
}

export function createService(body: ServiceCreate): Promise<ServiceCreateResponse> {
  return request<ServiceCreateResponse>("/services", { method: "POST", body: JSON.stringify(body) });
}

export function patchService(id: string, body: ServicePatch): Promise<ServiceOut> {
  return request<ServiceOut>(`/services/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

/** Soft delete (default) or, with `purge`, a hard delete of the
 * registration + its keys — never of telemetry history either way (see
 * api/app/registry/service.py::delete_service). */
export function deleteService(id: string, purge = false): Promise<void> {
  return request<void>(`/services/${id}${purge ? "?purge=true" : ""}`, { method: "DELETE" });
}

export function createKey(serviceId: string, label: string | null): Promise<KeyCreateResponse> {
  return request<KeyCreateResponse>(`/services/${serviceId}/keys`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function revokeKey(serviceId: string, keyId: string): Promise<void> {
  return request<void>(`/services/${serviceId}/keys/${keyId}`, { method: "DELETE" });
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
