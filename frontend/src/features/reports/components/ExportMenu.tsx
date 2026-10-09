import { AlertTriangle, CheckCircle2, Download, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Progress } from '@/components/ui/progress'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { ExportState } from '../hooks/useCsvExport'
import { EXPORTS, ignoredFilters, type ExportDef } from '../lib/exports'
import type { ReportFilters } from '../api/types'

/** "Export CSV" menu listing every exportable report; each entry says which active filters it ignores. */
export function ExportMenu({
  filters,
  busy,
  onExport,
}: {
  filters: ReportFilters
  busy: boolean
  onExport: (def: ExportDef) => void
}) {
  const { user } = useAuth()
  const available = EXPORTS.filter((e) => !user || !e.hiddenFor?.includes(user.role))
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" disabled={busy}>
          <Download /> Export CSV
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Download a report as CSV</DropdownMenuLabel>
        {available.map((def) => {
          const ignored = ignoredFilters(def, filters)
          return (
            <DropdownMenuItem key={def.id} onSelect={() => onExport(def)} className="items-start">
              <span className="min-w-0">
                <span className="block font-medium">{def.label}</span>
                <span className="block text-xs text-muted-foreground">{def.description}</span>
                {ignored && <span className="block text-xs text-muted-foreground italic">{ignored}</span>}
              </span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Live status of the current export: progress while it runs, the saved file name, or a retryable error. */
export function ExportStatus({
  state,
  onRetry,
  onDismiss,
}: {
  state: ExportState
  onRetry: (def: ExportDef) => void
  onDismiss: () => void
}) {
  if (state.status === 'idle') return null
  if (state.status === 'error') {
    return (
      <div
        role="alert"
        className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-red-500/30 bg-red-500/8 p-3.5 text-sm"
      >
        <AlertTriangle className="size-4.5 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
        <p className="min-w-0 flex-1">
          <span className="font-semibold">Export failed: {state.def.label}.</span> {state.message}
        </p>
        <Button size="sm" variant="outline" onClick={() => onRetry(state.def)}>
          Try again
        </Button>
        <Button size="icon-sm" variant="ghost" onClick={onDismiss} aria-label="Dismiss export message">
          <X />
        </Button>
      </div>
    )
  }
  if (state.status === 'running') {
    const background = state.def.mode === 'task'
    return (
      <div role="status" className="mb-5 space-y-2 rounded-lg border bg-card p-3.5 text-sm">
        <p className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          <span>
            {background ? 'Preparing' : 'Downloading'} <strong>{state.def.label}</strong> CSV
            {state.stage ? ` (${state.stage})` : ''}…
          </span>
        </p>
        {background && state.progress !== null && (
          <Progress value={state.progress} label={`Export progress, ${Math.round(state.progress)} percent`} />
        )}
      </div>
    )
  }
  return (
    <div
      role="status"
      className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/8 p-3.5 text-sm"
    >
      <CheckCircle2 className="size-4.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
      <p className="min-w-0 flex-1">
        {state.filename ? (
          <>
            Saved <strong>{state.filename}</strong>.
          </>
        ) : (
          <>
            Downloaded <strong>{state.def.label}</strong> as CSV.
          </>
        )}
        {state.note ? ` ${state.note}` : ''}
      </p>
      <Button size="icon-sm" variant="ghost" onClick={onDismiss} aria-label="Dismiss export message">
        <X />
      </Button>
    </div>
  )
}
