import { useEffect, useState } from "react";

import { getToken, subscribeToken } from "@/lib/auth";

export function useAuthToken(): string | null {
  const [token, setTokenState] = useState(getToken());

  useEffect(() => subscribeToken(setTokenState), []);

  return token;
}
