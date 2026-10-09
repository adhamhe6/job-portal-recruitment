import { CalendarClock, GripVertical } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { MatchScoreBadge } from '@/components/common/MatchScore'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import type { ApplicationListItem, ApplicationStatus } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { dates } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { ALL_STAGES, staffTargets } from '../lib/workflow'
import { MoveMenu } from './MoveMenu'

const COLUMN_TONE: Record<ApplicationStatus, string> = {
  APPLIED: 'bg-sky-500',
  SCREENING: 'bg-violet-500',
  SHORTLISTED: 'bg-primary',
  INTERVIEW: 'bg-amber-500',
  OFFER: 'bg-orange-500',
  HIRED: 'bg-emerald-500',
  REJECTED: 'bg-red-500',
  WITHDRAWN: 'bg-muted-foreground',
}

type Move = (app: ApplicationListItem, target: ApplicationStatus) => void

function BoardCard({
  app,
  onMove,
  busy,
  onDragStart,
  onDragEnd,
}: {
  app: ApplicationListItem
  onMove: Move
  busy: boolean
  onDragStart: (app: ApplicationListItem) => void
  onDragEnd: () => void
}) {
  const { can } = useAuth()
  const draggable = can('manage_applications') && staffTargets(app.status).length > 0
  return (
    <li
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', app.id)
        e.dataTransfer.effectAllowed = 'move'
        onDragStart(app)
      }}
      onDragEnd={onDragEnd}
      aria-busy={busy || undefined}
      className={cn(
        'group rounded-lg border bg-card p-3 shadow-xs transition-opacity',
        draggable && 'cursor-grab active:cursor-grabbing',
        busy && 'opacity-60',
      )}
    >
      <div className="flex items-start gap-1.5">
        {draggable && (
          <GripVertical
            className="mt-0.5 size-4 shrink-0 text-muted-foreground/60 max-md:hidden"
            aria-hidden
          />
        )}
        <div className="min-w-0 flex-1">
          <Link
            to={paths.application(app.id)}
            className="block truncate rounded-sm text-sm font-medium hover:text-primary hover:underline"
          >
            {app.candidate_name}
          </Link>
          <p className="truncate text-xs text-muted-foreground">{app.job_title}</p>
        </div>
        <MoveMenu
          name={app.candidate_name}
          status={app.status}
          disabled={busy}
          onMove={(t) => onMove(app, t)}
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <MatchScoreBadge score={app.match_score} band={app.match_band} />
        <span title={dates.dateTime(app.applied_at)}>Applied {dates.relative(app.applied_at)}</span>
      </div>
      {app.next_interview_at && (
        <p className="mt-1.5 flex items-center gap-1 text-xs text-foreground">
          <CalendarClock className="size-3.5 text-muted-foreground" aria-hidden />
          Interview {dates.dateTime(app.next_interview_at)}
        </p>
      )}
    </li>
  )
}

/**
 * Kanban-style pipeline. Cards can be dragged onto a valid column (mouse/touch-capable browsers), and every card has
 * a "Move" menu that offers exactly the same moves from the keyboard. Columns scroll horizontally inside the board.
 */
export function PipelineBoard({
  items,
  loading,
  pendingId,
  onMove,
}: {
  items: ApplicationListItem[] | undefined
  loading?: boolean
  pendingId: string | null
  onMove: Move
}) {
  const { can } = useAuth()
  const [dragging, setDragging] = useState<ApplicationListItem | null>(null)
  const [over, setOver] = useState<ApplicationStatus | null>(null)

  const columns = useMemo(() => {
    const by = new Map<ApplicationStatus, ApplicationListItem[]>(ALL_STAGES.map((s) => [s, []]))
    for (const a of items ?? []) by.get(a.status)?.push(a)
    return by
  }, [items])

  const validTargets = dragging && can('manage_applications') ? staffTargets(dragging.status) : []

  return (
    <div
      className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-3 sm:mx-0 sm:px-0"
      role="group"
      aria-label="Hiring pipeline"
    >
      {ALL_STAGES.map((status) => {
        const list = columns.get(status) ?? []
        const droppable = validTargets.includes(status)
        const headingId = `col-${status}`
        return (
          <section
            key={status}
            aria-labelledby={headingId}
            onDragOver={(e) => {
              if (!droppable) return
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              setOver(status)
            }}
            onDragLeave={() => setOver((o) => (o === status ? null : o))}
            onDrop={(e) => {
              e.preventDefault()
              setOver(null)
              if (dragging && droppable) onMove(dragging, status)
              setDragging(null)
            }}
            className={cn(
              'flex max-h-[70vh] w-72 shrink-0 snap-start flex-col rounded-xl border bg-surface p-2 transition-colors',
              dragging && droppable && 'border-primary/50 bg-primary-soft/40',
              over === status && 'ring-2 ring-primary',
              dragging && !droppable && dragging.status !== status && 'opacity-60',
            )}
          >
            <h3 className="flex items-center gap-2 px-2 py-1.5 text-sm font-semibold">
              <span className={cn('size-2 rounded-full', COLUMN_TONE[status])} aria-hidden />
              <span id={headingId}>{APPLICATION_STATUS_LABELS[status]}</span>
              <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular">
                {loading && !items ? '–' : list.length}
                <span className="sr-only"> applications</span>
              </span>
            </h3>
            {loading && !items ? (
              <div className="space-y-2 p-1" role="status" aria-label="Loading applications">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : list.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                {droppable ? 'Drop here to move' : 'No applications'}
              </p>
            ) : (
              <ul
                className="min-h-0 flex-1 space-y-2 overflow-y-auto p-1"
                aria-label={`${APPLICATION_STATUS_LABELS[status]} applications`}
              >
                {list.map((a) => (
                  <BoardCard
                    key={a.id}
                    app={a}
                    onMove={onMove}
                    busy={pendingId === a.id}
                    onDragStart={setDragging}
                    onDragEnd={() => {
                      setDragging(null)
                      setOver(null)
                    }}
                  />
                ))}
              </ul>
            )}
          </section>
        )
      })}
    </div>
  )
}
