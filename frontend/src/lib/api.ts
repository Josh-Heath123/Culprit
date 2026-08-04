// Thin fetch + JSON + error-shaping wrapper only — retries, caching, and
// background refetch are all TanStack Query's job (see src/hooks/), not
// reimplemented here.

import type { IncidentDetail, PaginatedIncidents } from "@/lib/types";

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
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body || response.statusText, response.status);
  }
  if (response.status === 204 || response.status === 202) {
    return undefined as T;
  }
  return (await response.json()) as T;
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
