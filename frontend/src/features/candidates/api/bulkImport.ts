import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, upload, type Paginated } from '@/lib/api'
import { candidateKeys } from './candidates'

/**
 * Bulk résumé import (POST/GET /resumes/bulk-imports). These endpoints are not in the generated OpenAPI schema yet, so the
 * minimal shapes we depend on are declared here, mirroring backend/app/schemas/resume.py (BulkImport*).
 */
export type BatchStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
export type ImportItemStatus = 'PENDING' | 'CREATED' | 'DUPLICATE' | 'FAILED'

export interface BulkImportCounts {
  pending: number
  created: number
  duplicate: number
  failed: number
}
export interface BulkImportItem {
  id: string
  filename: string
  size_bytes: number
  status: ImportItemStatus
  candidate_id?: string | null
  resume_id?: string | null
  error_code?: string | null
  error_message?: string | null
}
export interface BulkImportBatch {
  id: string
  status: BatchStatus
  total_files: number
  counts: BulkImportCounts
  task_id?: string | null
  progress?: number | null
  created_at: string
  finished_at?: string | null
}
export interface BulkImportBatchDetail extends BulkImportBatch {
  items: BulkImportItem[]
}
export interface RejectedFile {
  filename: string
  reason: string
  code?: string | null
}
export interface BulkImportAccepted {
  batch_id: string
  task_id?: string | null
  accepted: number
  rejected: RejectedFile[]
  message?: string | null
}

export const bulkImportKeys = {
  all: ['bulk-imports'] as const,
  list: (page: number) => ['bulk-imports', 'list', page] as const,
  detail: (id: string) => ['bulk-imports', 'detail', id] as const,
}

export const isBatchActive = (b: Pick<BulkImportBatch, 'status'> | undefined) =>
  b?.status === 'PENDING' || b?.status === 'RUNNING'

/** Batch with per-file outcomes. Polls every `intervalMs` while the background task is still working. */
export function useBulkImportBatch(batchId: string | null | undefined, intervalMs = 2000) {
  return useQuery({
    queryKey: bulkImportKeys.detail(batchId ?? ''),
    enabled: Boolean(batchId),
    queryFn: ({ signal }) =>
      api.get<BulkImportBatchDetail>(`/resumes/bulk-imports/${batchId}`, undefined, { signal }),
    refetchInterval: (q) => (q.state.data && !isBatchActive(q.state.data) ? false : intervalMs),
    staleTime: 0,
  })
}

/** My company's recent import batches, newest first. */
export function useBulkImportBatches(page = 1, enabled = true) {
  return useQuery({
    queryKey: bulkImportKeys.list(page),
    enabled,
    queryFn: ({ signal }) =>
      api.get<Paginated<BulkImportBatch>>('/resumes/bulk-imports', { page, page_size: 5 }, { signal }),
    placeholderData: keepPreviousData,
  })
}

/** Upload one multipart request of résumé files (field `files`, repeated). */
export function useBulkImportUpload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ files, onProgress }: { files: File[]; onProgress?: (fraction: number) => void }) => {
      const form = new FormData()
      for (const f of files) form.append('files', f, f.name)
      return upload<BulkImportAccepted>('/resumes/bulk-imports', form, { onProgress })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: bulkImportKeys.all }),
  })
}

/** Re-queue a batch whose task was lost or never queued. Only items still PENDING are processed. */
export function useReprocessBatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (batchId: string) =>
      api.post<{ task_id: string }>(`/resumes/bulk-imports/${batchId}/process`),
    onSettled: (_d, _e, batchId) => qc.invalidateQueries({ queryKey: bulkImportKeys.detail(batchId) }),
  })
}

/** New candidates may now be searchable. */
export function useInvalidateCandidates() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: candidateKeys.all })
}
