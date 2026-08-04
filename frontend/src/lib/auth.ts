// In-memory only, deliberately never localStorage/sessionStorage: this is
// a JWT session token, and both storages are readable by any script that
// runs on the page (XSS blast radius). A page refresh means logging in
// again — that trade-off is intentional. lib/api.ts's request() wrapper
// reads getToken() on every call; components read the token via
// hooks/useAuth.ts's useAuthToken() to decide whether to render the
// login screen or the dashboard (see App.tsx).

type Listener = (token: string | null) => void;

let token: string | null = null;
const listeners = new Set<Listener>();

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null): void {
  token = next;
  listeners.forEach((listener) => listener(token));
}

export function subscribeToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
