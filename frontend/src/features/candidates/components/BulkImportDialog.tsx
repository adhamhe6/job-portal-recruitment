import { FileText, UploadCloud, X } from 'lucide-react'
import { useId, useRef, useState, type DragEvent } from 'react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, errorMessage } from '@/lib/api'
import { dates, fmt } from '@/lib/format'
import { cn, pluralize } from '@/lib/utils'
import {
  isBatchActive,
  useBulkImportBatches,
  useBulkImportUpload,
  type RejectedFile,
} from '../api/bulkImport'
import {
  BULK_ACCEPT,
  BULK_MAX_FILE_MB,
  BULK_MAX_FILES,
  chunkFiles,
  formatBytes,
  pickFiles,
  type PickResult,
} from '../lib/bulkImport'
import { BatchProgress } from './BatchProgress'

function uploadErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return 'Your account is not allowed to import résumés.'
    if (e.status === 413) return 'The upload was too large. Try fewer files at a time.'
    if (e.status === 429) return 'Too many uploads in a short time. Please wait a moment and try again.'
    if (e.is('NO_VALID_FILES')) return 'None of the selected files could be accepted. See the reasons below.'
  }
  return errorMessage(e)
}

/**
 * Bulk résumé import for recruiters: pick many PDF/DOCX files, upload them (split into request-sized groups),
 * then follow each batch's background processing file by file.
 */
export function BulkImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [problems, setProblems] = useState<PickResult['problems']>([])
  const [dragging, setDragging] = useState(false)
  const [batchIds, setBatchIds] = useState<string[]>([])
  const [rejected, setRejected] = useState<RejectedFile[]>([])
  const [uploadError, setUploadError] = useState<unknown>(null)
  const [progress, setProgress] = useState<{ part: number; parts: number; fraction: number } | null>(null)
  const upload = useBulkImportUpload()
  const recent = useBulkImportBatches(1, open)

  const take = (list: FileList | File[] | null | undefined) => {
    if (!list || list.length === 0) return
    const result = pickFiles(files, Array.from(list))
    setFiles((cur) => [...cur, ...result.accepted])
    setProblems(result.problems)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (!upload.isPending) take(e.dataTransfer.files)
  }

  const submit = async () => {
    setUploadError(null)
    setRejected([])
    const parts = chunkFiles(files)
    let remaining = files
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]!
      setProgress({ part: i + 1, parts: parts.length, fraction: 0 })
      try {
        const res = await upload.mutateAsync({
          files: part,
          onProgress: (fraction) => setProgress({ part: i + 1, parts: parts.length, fraction }),
        })
        setBatchIds((ids) => [res.batch_id, ...ids])
        setRejected((r) => [...r, ...res.rejected])
        remaining = remaining.slice(part.length)
        setFiles(remaining)
      } catch (e) {
        setUploadError(e)
        // Files the server rejected individually come back inside the error details when nothing was valid.
        break
      }
    }
    setProgress(null)
  }

  const busy = upload.isPending
  const totalBytes = files.reduce((n, f) => n + f.size, 0)
  const watched = new Set(batchIds)
  const history = (recent.data?.items ?? []).filter((b) => !watched.has(b.id))

  return (
    <Dialog open={open} onOpenChange={(o) => (!busy ? onOpenChange(o) : undefined)}>
      <DialogContent size="xl" aria-describedby="bulk-import-desc">
        <DialogHeader>
          <DialogTitle>Bulk résumé import</DialogTitle>
          <DialogDescription id="bulk-import-desc">
            Add PDF or DOCX résumés (up to {BULK_MAX_FILES} files, {BULK_MAX_FILE_MB} MB each). Each new
            résumé becomes a private candidate visible only to your company. Duplicates are skipped, and
            unreadable files are reported without stopping the rest.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <label
            htmlFor={inputId}
            onDragOver={(e) => {
              e.preventDefault()
              if (!busy) setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-input bg-surface px-6 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring hover:border-primary/50 hover:bg-primary-soft/40',
              dragging && 'border-primary bg-primary-soft/60',
              busy && 'pointer-events-none opacity-60',
            )}
          >
            <UploadCloud className="size-8 text-primary" aria-hidden />
            <span className="text-sm font-medium">Drop résumés here, or click to choose files</span>
            <span className="text-xs text-muted-foreground">PDF or DOCX · you can select many at once</span>
            <input
              ref={inputRef}
              id={inputId}
              type="file"
              multiple
              className="sr-only"
              accept={BULK_ACCEPT.join(',')}
              disabled={busy}
              onChange={(e) => {
                take(e.target.files)
                e.target.value = ''
              }}
            />
          </label>

          {problems.length > 0 && (
            <div
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"
            >
              <p className="font-medium text-destructive">
                {problems.length} {pluralize(problems.length, 'file')} not added
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
                {problems.slice(0, 8).map((p, i) => (
                  <li key={`${p.name}-${i}`}>
                    <span className="font-medium text-foreground">{p.name}</span>: {p.reason}
                  </li>
                ))}
                {problems.length > 8 && <li>and {problems.length - 8} more</li>}
              </ul>
            </div>
          )}

          {files.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="font-medium">
                  {fmt.int(files.length)} {pluralize(files.length, 'file')} selected
                  <span className="font-normal text-muted-foreground"> · {formatBytes(totalBytes)}</span>
                </span>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => setFiles([])}>
                  Remove all
                </Button>
              </div>
              <ul
                className="max-h-44 divide-y overflow-y-auto rounded-lg border px-3"
                aria-label="Selected résumés"
              >
                {files.map((f) => (
                  <li key={`${f.name}:${f.size}`} className="flex items-center gap-2 py-1.5 text-sm">
                    <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate" title={f.name}>
                      {f.name}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(f.size)}</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={busy}
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles((cur) => cur.filter((x) => x !== f))}
                    >
                      <X />
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {progress && (
            <div className="space-y-1" role="status">
              <p className="text-sm text-muted-foreground">
                Uploading{progress.parts > 1 ? ` part ${progress.part} of ${progress.parts}` : ''}…
              </p>
              <Progress value={progress.fraction * 100} label="Upload progress" />
            </div>
          )}

          {uploadError != null && (
            <Alert variant="danger" title="Upload failed">
              {uploadErrorMessage(uploadError)}
            </Alert>
          )}
          {uploadError instanceof ApiError &&
            Array.isArray(uploadError.details) &&
            uploadError.details.length > 0 && (
              <ul className="list-disc pl-5 text-sm text-muted-foreground">
                {uploadError.detailMessages.slice(0, 6).map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            )}

          {rejected.length > 0 && (
            <Alert
              variant="warning"
              title={`${rejected.length} ${pluralize(rejected.length, 'file')} rejected by the server`}
            >
              <ul>
                {rejected.map((r, i) => (
                  <li key={`${r.filename}-${i}`}>
                    <span className="font-medium">{r.filename}</span>: {r.reason}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
        </div>

        {batchIds.length > 0 && (
          <div className="space-y-3">
            {batchIds.map((id, i) => (
              <BatchProgress
                key={id}
                batchId={id}
                title={batchIds.length > 1 ? `Import ${batchIds.length - i}` : 'Import progress'}
              />
            ))}
          </div>
        )}

        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Recent imports</h3>
          {recent.isPending ? (
            <Skeleton className="h-10 w-full" />
          ) : recent.isError ? (
            <p className="text-sm text-muted-foreground">
              Recent imports could not be loaded.{' '}
              <button
                type="button"
                className="font-medium text-primary hover:underline"
                onClick={() => void recent.refetch()}
              >
                Try again
              </button>
            </p>
          ) : history.length === 0 ? (
            <p className="text-sm text-muted-foreground">No earlier imports.</p>
          ) : (
            <ul className="divide-y rounded-lg border px-3" aria-label="Recent imports">
              {history.map((b) => (
                <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    {fmt.int(b.total_files)} {pluralize(b.total_files, 'file')} ·{' '}
                    {dates.relative(b.created_at)} ·{' '}
                    <span className="text-muted-foreground">
                      {isBatchActive(b)
                        ? 'processing'
                        : `${fmt.int(b.counts.created)} imported, ${fmt.int(b.counts.failed)} failed`}
                    </span>
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setBatchIds((ids) => [b.id, ...ids])}>
                    View details
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Close
          </Button>
          <Button onClick={() => void submit()} loading={busy} disabled={files.length === 0}>
            <UploadCloud /> Import {files.length > 0 ? fmt.int(files.length) : ''}{' '}
            {pluralize(files.length, 'résumé')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
