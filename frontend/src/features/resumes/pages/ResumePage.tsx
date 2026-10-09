import { FileText } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ApiError, errorMessage } from '@/lib/api'
import { paths } from '@/routes/paths'
import {
  downloadResume,
  isResumeBusy,
  useDeleteResume,
  useMyResumes,
  useReprocessResume,
  useSetPrimaryResume,
  type ResumeOut,
} from '../api/resumes'
import { ResumeCard } from '../components/ResumeCard'
import { ReviewPanel } from '../components/ReviewPanel'
import { UploadCard } from '../components/UploadCard'

function deleteMessage(e: unknown): string {
  if (e instanceof ApiError && e.code === 'RESUME_IN_USE')
    return 'This résumé is attached to one of your applications, so it cannot be deleted. Upload a new one and make it primary instead.'
  return errorMessage(e)
}

export default function ResumePage() {
  useDocumentTitle('My résumé')
  const resumes = useMyResumes()
  const [{ review }, update] = useUrlState({ review: '' })
  const setPrimary = useSetPrimaryResume()
  const reprocess = useReprocessResume()
  const del = useDeleteResume()
  const [running, setRunning] = useState<{ id: string; action: string } | null>(null)
  const [toDelete, setToDelete] = useState<ResumeOut | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const data = resumes.data
  const list = useMemo(() => data ?? [], [data])

  // Announce when a background run finishes (the list polls while any résumé is busy).
  const seen = useRef<Map<string, string>>(new Map())
  useEffect(() => {
    for (const r of list) {
      const before = seen.current.get(r.id)
      if (before && (before === 'UPLOADED' || before === 'PROCESSING') && r.status === 'PROCESSED') {
        toast.success('Résumé processed', {
          description: `${r.original_filename} is ready to review.`,
          action: { label: 'Review', onClick: () => update({ review: r.id }) },
        })
      } else if (before && (before === 'UPLOADED' || before === 'PROCESSING') && r.status === 'FAILED') {
        toast.error('Résumé processing failed', {
          description: r.processing.error_message ?? r.original_filename,
        })
      }
      seen.current.set(r.id, r.status)
    }
  }, [list, update])

  const reviewing = list.find((r) => r.id === review)

  const act = async (r: ResumeOut, action: string, fn: () => Promise<unknown>, success?: string) => {
    setRunning({ id: r.id, action })
    try {
      await fn()
      if (success) toast.success(success)
    } catch (e) {
      toast.error('Something went wrong', { description: errorMessage(e) })
    } finally {
      setRunning(null)
    }
  }

  const confirmDelete = async () => {
    if (!toDelete) return
    setDeleteError(null)
    try {
      await del.mutateAsync(toDelete.id)
      toast.success('Résumé deleted', { description: toDelete.original_filename })
      if (review === toDelete.id) update({ review: '' })
      setToDelete(null)
    } catch (e) {
      setDeleteError(deleteMessage(e))
    }
  }

  return (
    <>
      <PageHeader
        title="My résumé"
        description="Upload your résumé, keep a primary version for applications, and review what we extracted before it touches your profile."
        actions={
          <Button asChild variant="outline">
            <Link to={paths.profile}>Edit profile</Link>
          </Button>
        }
      />

      <div className="grid gap-6">
        <UploadCard hasResumes={list.length > 0} />

        <section aria-labelledby="your-resumes" className="grid gap-3">
          <h2 id="your-resumes" className="text-lg font-semibold">
            Your résumés
          </h2>
          {resumes.isPending ? (
            <div className="grid gap-3" role="status" aria-busy="true" aria-label="Loading résumés">
              <Skeleton className="h-32 w-full rounded-xl" />
              <Skeleton className="h-32 w-full rounded-xl" />
            </div>
          ) : resumes.isError ? (
            <ErrorState
              error={resumes.error}
              onRetry={() => resumes.refetch()}
              title="Couldn't load your résumés"
            />
          ) : list.length === 0 ? (
            <div className="rounded-xl border border-dashed">
              <EmptyState
                icon={<FileText aria-hidden />}
                title="No résumé uploaded yet"
                description="Upload a PDF or Word file above. Recruiters rely on it, and it lets us suggest skills and experience for your profile."
              />
            </div>
          ) : (
            <ul className="grid gap-3" aria-label="Your résumés" aria-busy={list.some(isResumeBusy)}>
              {list.map((r) => (
                <ResumeCard
                  key={r.id}
                  resume={r}
                  reviewing={review === r.id}
                  busyAction={running?.id === r.id ? running.action : null}
                  onReview={() => update({ review: review === r.id ? '' : r.id })}
                  onDownload={() => act(r, 'download', () => downloadResume(r))}
                  onMakePrimary={() =>
                    act(
                      r,
                      'primary',
                      () => setPrimary.mutateAsync(r.id),
                      `${r.original_filename} is now your primary résumé`,
                    )
                  }
                  onReprocess={() =>
                    act(r, 'reprocess', () => reprocess.mutateAsync(r.id), 'Processing started again')
                  }
                  onDelete={() => {
                    setDeleteError(null)
                    setToDelete(r)
                  }}
                />
              ))}
            </ul>
          )}
        </section>

        {review &&
          resumes.isSuccess &&
          (reviewing ? (
            <ReviewPanel resume={reviewing} onClose={() => update({ review: '' })} />
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              That résumé no longer exists.{' '}
              <Button variant="link" onClick={() => update({ review: '' })}>
                Close review
              </Button>
            </p>
          ))}
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Delete this résumé?"
        description={
          <>
            <span className="font-medium break-all">{toDelete?.original_filename}</span> and its extracted
            data will be permanently deleted.
            {toDelete?.is_primary && ' Your newest remaining résumé becomes the primary one.'}
          </>
        }
        confirmLabel="Delete résumé"
        destructive
        loading={del.isPending}
        onConfirm={confirmDelete}
      >
        {deleteError && (
          <p role="alert" className="text-sm text-destructive">
            {deleteError}
          </p>
        )}
      </ConfirmDialog>
    </>
  )
}
