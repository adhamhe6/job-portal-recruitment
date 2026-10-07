import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { api, type Paginated, type SkillCreate, type SkillOut } from '@/lib/api'

export const skillKeys = { search: (q: string) => ['skills', 'search', q] as const }

/** Autocomplete against GET /skills?q= (matches names and aliases, e.g. "postgres" finds PostgreSQL). */
export function useSkillSearch(q: string, enabled = true, limit = 12) {
  return useQuery({
    queryKey: skillKeys.search(q.trim().toLowerCase()),
    queryFn: ({ signal }) => api.get<Paginated<SkillOut>>('/skills', { q: q.trim() || undefined, page_size: limit }, { signal }),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}

export function useCreateSkill() {
  return useMutation({ mutationFn: (body: SkillCreate) => api.post<SkillOut>('/skills', body) })
}
