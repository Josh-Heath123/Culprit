import { apiRequest } from "./client";

export interface Order {
  id: number;
  customer_email: string;
  total_cents: number;
  status: string;
}

export function listOrders(): Promise<Order[]> {
  return apiRequest<Order[]>("/api/v1/orders");
}

export function getOrder(id: number): Promise<Order> {
  return apiRequest<Order>(`/api/v1/orders/${id}`);
}

export function createOrder(body: Partial<Order>): Promise<Order> {
  return apiRequest<Order>("/api/v1/orders", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function cancelOrder(id: number): Promise<void> {
  return apiRequest<void>(`/api/v1/orders/${id}`, { method: "DELETE" });
}

// A call to a route the API does not serve. Left in deliberately: it is
// exactly the divergence Phase 29 exists to find, and a fixture with no
// disagreement in it proves nothing about a comparator.
export function searchOrders(query: string): Promise<Order[]> {
  return apiRequest<Order[]>(`/api/v2/orders/search?q=${query}`);
}
