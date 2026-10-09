import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  ApiError,
  downloadFile,
  upload,
  type components,
  type EducationLevel,
  type Paginated,
} from '@/lib/api'
import { useAuth } from '@/features/auth/hooks/useAuth'

type SkillStatus = components['schemas']['SkillStatus']
type LanguageProficiency = components['schemas']['LanguageProficiency']
type TaskRef = components['schemas']['TaskRef']

/**
 * Résumé API. The checked-in OpenAPI snapshot (`schema.d.ts`) predates the résumé module, so the shapes below mirror
 * `backend/app/schemas/resume.py` by hand. Replace them with the generated types after the next `npm run gen:api`.
 */

/** Minimal shape the apply flow depends on (ApplyDialog). `ResumeOut` satisfies it. */
export interface ResumeSummary {
  id: string
  original_filename?: string | null
  is_primary?: boolean
  status?: string
  created_at?: string
}

export type ResumeStatus = 'UPLOADED' | 'PROCESSING' | 'PROCESSED' | 'FAILED'
export type TaskStatusValue = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface ResumeProcessing {
  task_id?: string | null
  task_status?: TaskStatusValue | null
  stage?: string | null
  progress?: number | null
  attempts?: number | null
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  parser_version?: string | null
  page_count?: number | null
  text_char_count?: number | null
  was_truncated?: boolean
  has_embedding?: boolean
  error_code?: string | null
  error_message?: string | null
}

export interface ResumeOut extends ResumeSummary {
  id: string
  candidate_id: string
  status: ResumeStatus
  is_primary: boolean
  original_filename: string
  content_type: string
  size_bytes: number
  sha256: string
  created_at: string
  updated_at: string
  task_id?: string | null
  processing: ResumeProcessing
}

export interface ResumeUploadOut extends ResumeOut {
  message?: string | null
  duplicate: boolean
}

// --- extracted suggestions -------------------------------------------------------------------------------------------

export interface ExtractedContact {
  name?: string | null
  email?: string | null
  phone?: string | null
  linkedin_url?: string | null
  github_url?: string | null
  portfolio_url?: string | null
  location?: string | null
}
export interface ExtractedSkill {
  index: number
  name: string
  skill_id?: string | null
  confidence: number
  listed: boolean
  already_on_profile: boolean
  status?: SkillStatus | null
  corrected: boolean
}
export interface ExtractedExperience {
  index: number
  title?: string | null
  company?: string | null
  location?: string | null
  start_date?: string | null
  end_date?: string | null
  is_current: boolean
  description?: string | null
  confidence: number
  already_on_profile: boolean
  corrected: boolean
  missing_for_apply: string[]
}
export interface ExtractedEducation {
  index: number
  institution?: string | null
  degree?: string | null
  degree_level?: EducationLevel | null
  field_of_study?: string | null
  start_year?: number | null
  end_year?: number | null
  confidence: number
  already_on_profile: boolean
  corrected: boolean
  missing_for_apply: string[]
}
export interface ExtractedCertification {
  index: number
  name: string
  issuer?: string | null
  issued_on?: string | null
  issued_year?: number | null
  confidence: number
  already_on_profile: boolean
  corrected: boolean
}
export interface ExtractedLanguage {
  index: number
  language: string
  proficiency?: LanguageProficiency | null
  confidence: number
  already_on_profile: boolean
  corrected: boolean
  missing_for_apply: string[]
}
export interface ExtractedResume {
  resume_id: string
  candidate_id: string
  parser_version: string
  has_corrections: boolean
  contact: ExtractedContact
  headline?: string | null
  summary?: string | null
  years_of_experience?: number | null
  years_basis?: string | null
  skills: ExtractedSkill[]
  experiences: ExtractedExperience[]
  educations: ExtractedEducation[]
  certifications: ExtractedCertification[]
  languages: ExtractedLanguage[]
  sections_detected: string[]
  warnings: string[]
}

export type ProfileField =
  | 'summary'
  | 'headline'
  | 'location'
  | 'years_experience'
  | 'linkedin_url'
  | 'github_url'
  | 'portfolio_url'
  | 'phone'

export interface ExtractedPatch {
  contact?: Partial<Record<keyof ExtractedContact, string | null>>
  headline?: string | null
  summary?: string | null
  years_of_experience?: number | null
  skills?: { index: number; remove?: boolean; name?: string }[]
  experiences?: {
    index: number
    remove?: boolean
    title?: string
    company?: string
    location?: string | null
    start_date?: string | null
    end_date?: string | null
    is_current?: boolean
    description?: string | null
  }[]
  educations?: {
    index: number
    remove?: boolean
    institution?: string
    degree?: string | null
    degree_level?: EducationLevel | null
    field_of_study?: string | null
    start_year?: number | null
    end_year?: number | null
  }[]
  certifications?: {
    index: number
    remove?: boolean
    name?: string
    issuer?: string | null
    issued_on?: string | null
  }[]
  languages?: {
    index: number
    remove?: boolean
    language?: string
    proficiency?: LanguageProficiency | null
  }[]
}

export interface ApplyRequest {
  skills?: number[] | 'all'
  experiences?: number[] | 'all'
  educations?: number[] | 'all'
  certifications?: number[] | 'all'
  languages?: number[] | 'all'
  fields?: ProfileField[]
  overwrite?: ProfileField[]
}
export interface ApplyResult {
  applied: Record<string, number>
  fields_applied: string[]
  skipped: { section: string; index?: number | null; reason: string }[]
}

// --- keys ------------------------------------------------------------------------------------------------------------

export const resumeKeys = {
  all: ['resumes'] as const,
  list: ['resumes', 'list'] as const,
  extracted: (id: string) => ['resumes', 'extracted', id] as const,
}

/** Polling cadence while a résumé is still being processed. */
export const RESUME_POLL_MS = 2_000

export const isResumeBusy = (r: Pick<ResumeOut, 'status'>) =>
  r.status === 'UPLOADED' || r.status === 'PROCESSING'

/** The candidate's résumés (primary first). While any is processing, the list refetches every 2 s. */
export function useMyResumes(enabled = true) {
  const { isCandidate } = useAuth()
  return useQuery({
    queryKey: resumeKeys.list,
    enabled: enabled && isCandidate,
    queryFn: async ({ signal }): Promise<ResumeOut[]> => {
      try {
        const data = await api.get<ResumeOut[] | Paginated<ResumeOut>>(
          '/resumes',
          { page_size: 50 },
          { signal },
        )
        return Array.isArray(data) ? data : (data?.items ?? [])
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return []
        throw e
      }
    },
    refetchInterval: (query) => (query.state.data?.some(isResumeBusy) ? RESUME_POLL_MS : false),
    staleTime: 30_000,
  })
}

function invalidateAfterResumeChange(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: resumeKeys.all })
  void qc.invalidateQueries({ queryKey: ['candidate'] }) // completion + primary résumé on the profile
  void qc.invalidateQueries({ queryKey: ['notifications'] })
}

export function useUploadResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      file,
      setPrimary,
      onProgress,
    }: {
      file: File
      setPrimary: boolean
      onProgress?: (fraction: number) => void
    }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('set_primary', String(setPrimary))
      return upload<ResumeUploadOut>('/resumes', form, { onProgress })
    },
    onSuccess: () => invalidateAfterResumeChange(qc),
  })
}

export function useSetPrimaryResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<ResumeOut>(`/resumes/${id}/primary`),
    onSuccess: () => invalidateAfterResumeChange(qc),
  })
}

export function useDeleteResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/resumes/${id}`),
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: resumeKeys.extracted(id) })
      invalidateAfterResumeChange(qc)
    },
  })
}

export function useReprocessResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<TaskRef>(`/resumes/${id}/process`),
    onSuccess: () => invalidateAfterResumeChange(qc),
  })
}

/** Authenticated download of the stored file (attachment). */
export function downloadResume(resume: Pick<ResumeOut, 'id' | 'original_filename'>) {
  return downloadFile(`/resumes/${resume.id}/file`, undefined, resume.original_filename)
}

/** Parser suggestions for a processed résumé (409 RESUME_NOT_PROCESSED until processing has finished). */
export function useExtracted(resumeId: string | null | undefined) {
  return useQuery({
    queryKey: resumeKeys.extracted(resumeId ?? ''),
    enabled: Boolean(resumeId),
    queryFn: ({ signal }) =>
      api.get<ExtractedResume>(`/resumes/${resumeId}/extracted`, undefined, { signal }),
    staleTime: 0,
  })
}

export function usePatchExtracted(resumeId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: ExtractedPatch) =>
      api.patch<ExtractedResume>(`/resumes/${resumeId}/extracted`, patch),
    onSuccess: (data) => qc.setQueryData(resumeKeys.extracted(resumeId), data),
  })
}

export function useApplyExtracted(resumeId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ApplyRequest) => api.post<ApplyResult>(`/resumes/${resumeId}/extracted/apply`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: resumeKeys.extracted(resumeId) })
      void qc.invalidateQueries({ queryKey: ['candidate'] })
      void qc.invalidateQueries({ queryKey: ['recommendations'] })
      void qc.invalidateQueries({ queryKey: ['matches'] })
    },
  })
}
