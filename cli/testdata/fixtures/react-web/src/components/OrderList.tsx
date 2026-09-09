import { useEffect, useState } from "react";

import { listOrders, type Order } from "../api/orders";

export function OrderList() {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    listOrders().then(setOrders);
  }, []);

  // A direct fetch, bypassing the wrapper — the shape the extractor
  // recognises without being told anything.
  useEffect(() => {
    fetch("/healthz").then(() => undefined);
  }, []);

  return (
    <ul>
      {orders.map((order) => (
        <li key={order.id}>
          {order.customer_email} — {order.total_cents}
        </li>
      ))}
    </ul>
  );
}
