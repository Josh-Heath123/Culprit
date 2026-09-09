// The wrapper every call goes through. Named to the extractor with
// --client-fn, because no generic tool can recognise a project-local one.
const API_URL = import.meta.env.VITE_API_URL ?? "/api";

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}
