import { useMutation, useQueryClient } from "@tanstack/react-query";

import { regenerateRootCause } from "@/lib/api";

export function useRegenerateRootCause(incidentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => regenerateRootCause(incidentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}
