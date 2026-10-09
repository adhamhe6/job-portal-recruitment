import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type {
  CandidateProfile,
  CandidateSkill,
  CandidateSkillIn,
  CandidateSkillUpdate,
  Certification,
  CertificationIn,
  Education,
  EducationIn,
  Experience,
  ExperienceIn,
  Language,
  LanguageIn,
  ProfileCompletion,
  ProfileUpdate,
} from '../lib/types'

/** Query keys: ['candidate', 'me'] (full profile) and ['candidate', 'completion']; invalidate ['candidate'] for both. */
export const profileKeys = {
  all: ['candidate'] as const,
  me: ['candidate', 'me'] as const,
  completion: ['candidate', 'completion'] as const,
}

export function useProfile() {
  const { isCandidate } = useAuth()
  return useQuery({
    queryKey: profileKeys.me,
    enabled: isCandidate,
    queryFn: ({ signal }) => api.get<CandidateProfile>('/candidates/me', undefined, { signal }),
  })
}

/** Lightweight completeness meter (also embedded in the full profile). */
export function useProfileCompletion() {
  const { isCandidate } = useAuth()
  return useQuery({
    queryKey: profileKeys.completion,
    enabled: isCandidate,
    queryFn: ({ signal }) => api.get<ProfileCompletion>('/candidates/me/completion', undefined, { signal }),
  })
}

/** Any profile change can alter matches/recommendations (the backend refreshes them in the background). */
function useAfterProfileChange() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: profileKeys.all })
    void qc.invalidateQueries({ queryKey: ['recommendations'] })
    void qc.invalidateQueries({ queryKey: ['matches'] })
  }
}

export function useUpdateProfile() {
  const after = useAfterProfileChange()
  return useMutation({
    mutationFn: (body: ProfileUpdate) => api.patch<CandidateProfile>('/candidates/me', body),
    onSuccess: after,
  })
}

type Section = 'experiences' | 'educations' | 'certifications' | 'languages'

function useSectionMutations<TIn, TOut>(section: Section, canUpdate = true) {
  const after = useAfterProfileChange()
  const base = `/candidates/me/${section}`
  return {
    create: useMutation({
      mutationFn: (body: TIn) => api.post<TOut>(base, body),
      onSuccess: after,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: TIn }) =>
        canUpdate ? api.put<TOut>(`${base}/${id}`, body) : Promise.reject(new Error('Not supported')),
      onSuccess: after,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete<void>(`${base}/${id}`),
      onSuccess: after,
    }),
  }
}

export const useExperienceMutations = () => useSectionMutations<ExperienceIn, Experience>('experiences')
export const useEducationMutations = () => useSectionMutations<EducationIn, Education>('educations')
export const useCertificationMutations = () =>
  useSectionMutations<CertificationIn, Certification>('certifications')
/** Languages have no PUT endpoint: editing is delete + add (handled by the section component). */
export const useLanguageMutations = () => useSectionMutations<LanguageIn, Language>('languages', false)

export function useSkillMutations() {
  const after = useAfterProfileChange()
  return {
    add: useMutation({
      mutationFn: (body: CandidateSkillIn) => api.post<CandidateSkill>('/candidates/me/skills', body),
      onSuccess: after,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: CandidateSkillUpdate }) =>
        api.patch<CandidateSkill>(`/candidates/me/skills/${id}`, body),
      onSuccess: after,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete<void>(`/candidates/me/skills/${id}`),
      onSuccess: after,
    }),
  }
}
