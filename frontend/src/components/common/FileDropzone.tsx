import { FileText, UploadCloud, X } from 'lucide-react'
import { useId, useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Drag-and-drop / click-to-browse file picker with client-side type and size validation.
 *
 *   <FileDropzone accept={['.pdf', '.docx']} maxSizeMB={10} onFile={setFile} file={file} progress={0.4} />
 *
 * `accept` is a list of extensions (".pdf") and/or MIME types. The real validation is server-side (magic bytes);
 * this only gives immediate feedback. Keyboard: the whole zone is a focusable label for the hidden input.
 */
export function FileDropzone({
  accept,
  maxSizeMB = 10,
  file,
  onFile,
  onClear,
  progress,
  disabled,
  title = 'Drop a file here, or click to browse',
  hint,
  className,
}: {
  accept?: string[]
  maxSizeMB?: number
  file?: File | null
  onFile: (file: File) => void
  onClear?: () => void
  /** 0..1 while uploading. */
  progress?: number | null
  disabled?: boolean
  title?: string
  hint?: string
  className?: string
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validate = (f: File): string | null => {
    if (accept?.length) {
      const name = f.name.toLowerCase()
      const ok = accept.some((a) => (a.startsWith('.') ? name.endsWith(a.toLowerCase()) : f.type === a || (a.endsWith('/*') && f.type.startsWith(a.slice(0, -1)))))
      if (!ok) return `Unsupported file type. Allowed: ${accept.join(', ')}`
    }
    if (f.size > maxSizeMB * 1024 * 1024) return `File is too large (${formatBytes(f.size)}). Maximum is ${maxSizeMB} MB.`
    if (f.size === 0) return 'The file is empty.'
    return null
  }

  const take = (f: File | undefined) => {
    if (!f) return
    const problem = validate(f)
    setError(problem)
    if (!problem) onFile(f)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (!disabled) take(e.dataTransfer.files[0])
  }

  const uploading = progress !== null && progress !== undefined && progress < 1

  return (
    <div className={cn('space-y-2', className)}>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault()
          if (!disabled) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-input bg-surface px-6 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring hover:border-primary/50 hover:bg-primary-soft/40',
          dragging && 'border-primary bg-primary-soft/60',
          disabled && 'pointer-events-none opacity-60',
        )}
      >
        <UploadCloud className="size-8 text-primary" aria-hidden />
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">
          {hint ?? `${accept?.length ? accept.join(', ').toUpperCase() : 'Any file'} · up to ${maxSizeMB} MB`}
        </span>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          className="sr-only"
          accept={accept?.join(',')}
          disabled={disabled}
          onChange={(e) => {
            take(e.target.files?.[0])
            e.target.value = '' // allow re-selecting the same file
          }}
        />
      </label>

      {error && (
        <p role="alert" className="text-sm font-medium text-destructive">
          {error}
        </p>
      )}

      {file && (
        <div className="flex items-center gap-3 rounded-lg border bg-card p-3">
          <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
            {uploading && <Progress className="mt-2" value={(progress ?? 0) * 100} label={`Uploading ${file.name}`} />}
          </div>
          {onClear && !uploading && (
            <Button variant="ghost" size="icon-sm" onClick={onClear} aria-label={`Remove ${file.name}`}>
              <X />
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
