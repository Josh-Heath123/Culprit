import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createPostmortem,
  deletePostmortem,
  fetchPostmortem,
  fetchPostmortems,
  patchPostmortem,
  retryPostmortemEmbedding,
} from "@/lib/api";
import type { PostmortemCreate, PostmortemOut, PostmortemPatch } from "@/lib/types";

const PAGE_SIZE = 20;

/** Same accumulate-pages convention as useIncidents.ts. A newly-written
 * postmortem's own mutation (useCreatePostmortem below) invalidates this
 * query directly, so the author sees it immediately regardless of the
 * poll interval — this refetch is for everyone else's tab. */
export function usePostmortems() {
  const query = useInfiniteQuery({
    queryKey: ["postmortems"],
    queryFn: ({ pageParam }) => fetchPostmortems(PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const loaded = lastPage.offset + lastPage.items.length;
      return loaded < lastPage.total ? loaded : undefined;
    },
    refetchInterval: 30_000,
  });

  const postmortems: PostmortemOut[] = query.data?.pages.flatMap((page) => page.items) ?? [];
  return { ...query, postmortems };
}

export function usePostmortem(id: string | undefined) {
  return useQuery({
    queryKey: ["postmortem", id],
    queryFn: () => fetchPostmortem(id as string),
    enabled: id !== undefined,
    // A postmortem mid-embedding is the one case this app polls a
    // detail view for — embedding_status flips pending -> embedded/failed
    // in the background (worker/app/rag/embed_job.py), and the editor
    // should reflect that without the user needing to reload.
    refetchInterval: (query) => (query.state.data?.embedding_status === "pending" ? 3_000 : false),
  });
}

function invalidatePostmortem(
  queryClient: ReturnType<typeof useQueryClient>,
  id: string | undefined,
) {
  queryClient.invalidateQueries({ queryKey: ["postmortems"] });
  if (id) queryClient.invalidateQueries({ queryKey: ["postmortem", id] });
}

export function useCreatePostmortem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PostmortemCreate) => createPostmortem(body),
    onSuccess: (result) => invalidatePostmortem(queryClient, result.id),
  });
}

export function usePatchPostmortem(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PostmortemPatch) => patchPostmortem(id, body),
    onSuccess: () => invalidatePostmortem(queryClient, id),
  });
}

export function useRetryPostmortemEmbedding(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => retryPostmortemEmbedding(id),
    onSuccess: () => invalidatePostmortem(queryClient, id),
  });
}

export function useDeletePostmortem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePostmortem(id),
    onSuccess: () => invalidatePostmortem(queryClient, undefined),
  });
}
