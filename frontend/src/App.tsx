import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { BrowserRouter } from "react-router-dom";

import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthToken } from "@/hooks/useAuth";
import { AppRoutes } from "@/routes/AppRoutes";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 5_000,
      // 'always' rather than the default 'online': this API is always
      // local/adjacent infra, never something that should sit paused
      // behind a browser online/offline heuristic that can lag or
      // misfire independent of whether the API is actually reachable.
      networkMode: "always",
    },
  },
});

function App() {
  const token = useAuthToken();

  // Drop any cached incident data on logout / session expiry — a fresh
  // login shouldn't briefly show whatever the previous session had
  // loaded before its own queries refetch.
  useEffect(() => {
    if (!token) queryClient.clear();
  }, [token]);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </TooltipProvider>
      {import.meta.env.DEV ? <ReactQueryDevtools initialIsOpen={false} /> : null}
    </QueryClientProvider>
  );
}

export default App;
