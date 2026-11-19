// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useState } from "react";

import { getToken, subscribeToken } from "@/lib/auth";

export function useAuthToken(): string | null {
  const [token, setTokenState] = useState(getToken());

  useEffect(() => subscribeToken(setTokenState), []);

  return token;
}
