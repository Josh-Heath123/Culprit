// Thin fetch + JSON + error-shaping wrapper only — retries, caching, and
// background refetch are all TanStack Query's job (see src/hooks/), not
// reimplemented here.

import { getToken, setToken } from "@/lib/auth";
import type {
  IncidentDetail,
  KeyCreateResponse,
  PaginatedIncidents,
  ServiceCreate,
  ServiceCreateResponse,
  ServiceOut,
  ServicePatch,
  ServicesOut,
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
  const data = (await response.json()) as { access_token: string };
  setToken(data.access_token);
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

// Phase 14: service registry — GET /services may be used by anyone
// authenticated (see api/app/registry/router.py); writes are the same
// require_auth gate today and will move to require_admin without any
// path change once Phase 16 lands (docs/SELF_HOSTED_PLAN.md).
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
