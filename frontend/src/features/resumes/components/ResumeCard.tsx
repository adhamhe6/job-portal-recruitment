import { Download, FileText, RefreshCw, Sparkles, Star, Trash2 } from 'lucide-react'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { dates, fmt } from '@/lib/format'
import { isResumeBusy, type ResumeOut } from '../api/resumes'

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ResumeCard({
  resume,
  reviewing,
  busyAction,
  onReview,
  onDownload,
  onMakePrimary,
  onReprocess,
  onDelete,
}: {
  resume: ResumeOut
  reviewing: boolean
  /** Which action is currently running for this résumé (disables its buttons). */
  busyAction: string | null
  onReview: () => void
  onDownload: () => void
  onMakePrimary: () => void
  onReprocess: () => void
  onDelete: () => void
}) {
  const busy = isResumeBusy(resume)
  const p = resume.processing
  const pct = p.progress ?? (resume.status === 'UPLOADED' ? 0 : 10)
  const name = resume.original_filename
  return (
    <li className="rounded-xl border bg-card p-4 shadow-xs sm:p-5">
      <div className="flex items-start gap-3">
        <FileText className="mt-0.5 size-6 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold break-all">{name}</h3>
            {resume.is_primary && (
              <Badge variant="solid">
                <Star aria-hidden /> Primary
              </Badge>
            )}
            <StatusBadge kind="resume" status={resume.status} />
          </div>
          <p className="text-xs text-muted-foreground">
            {formatBytes(resume.size_bytes)} · Uploaded {dates.relative(resume.created_at)}
            {p.page_count ? ` · ${p.page_count} page${p.page_count === 1 ? '' : 's'}` : ''}
          </p>

          {busy && (
            <div className="max-w-md space-y-1 pt-1" role="status">
              <Progress value={pct} label={`Processing ${name}`} />
              <p className="text-xs text-muted-foreground">
                {p.stage ? `${fmt.label(p.stage)}…` : 'Waiting to start…'} {Math.round(pct)}%
              </p>
            </div>
          )}

          {resume.status === 'FAILED' && (
            <Alert variant="danger" title="We couldn't read this résumé" className="mt-2">
              {p.error_message ?? 'Processing failed.'} Try again, or upload a text-based PDF or a .docx file.
            </Alert>
          )}
          {resume.status === 'PROCESSED' && p.was_truncated && (
            <p className="text-xs text-amber-800 dark:text-amber-300">
              This résumé is very long, so only the first part was analysed.
            </p>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 border-t pt-3">
        {resume.status === 'PROCESSED' && (
          <Button
            size="sm"
            variant={reviewing ? 'secondary' : 'default'}
            onClick={onReview}
            aria-pressed={reviewing}
          >
            <Sparkles /> {reviewing ? 'Reviewing suggestions' : 'Review suggestions'}
          </Button>
        )}
        {(resume.status === 'FAILED' || (resume.status === 'UPLOADED' && !resume.task_id)) && (
          <Button size="sm" onClick={onReprocess} loading={busyAction === 'reprocess'}>
            <RefreshCw /> Try again
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={onDownload}
          loading={busyAction === 'download'}
          aria-label={`Download ${name}`}
        >
          <Download /> Download
        </Button>
        {!resume.is_primary && (
          <Button
            size="sm"
            variant="outline"
            onClick={onMakePrimary}
            loading={busyAction === 'primary'}
            aria-label={`Make ${name} my primary résumé`}
          >
            <Star /> Make primary
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:text-destructive sm:ml-auto"
          onClick={onDelete}
          aria-label={`Delete ${name}`}
        >
          <Trash2 /> Delete
        </Button>
      </div>
    </li>
  )
}
