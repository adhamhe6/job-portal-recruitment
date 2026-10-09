import { ArrowRight, MoreHorizontal, Ban } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/hooks/useAuth'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { ApplicationStatus } from '@/lib/api'
import { APPLICATION_STATUS_LABELS } from '@/lib/enums'
import { moveLabel, staffTargets } from '../lib/workflow'

/**
 * Keyboard- and screen-reader-friendly way to move an application (the alternative to dragging a card). Only the
 * transitions the workflow allows are offered; terminal applications get an explanatory disabled item.
 */
export function MoveMenu({
  name,
  status,
  allowed,
  disabled,
  onMove,
  extra,
}: {
  name: string
  status: ApplicationStatus
  allowed?: ApplicationStatus[]
  disabled?: boolean
  onMove: (target: ApplicationStatus) => void
  /** Extra items rendered above the move items (e.g. "Open application"). */
  extra?: React.ReactNode
}) {
  const { can } = useAuth()
  const targets = staffTargets(status, allowed)
  if (!can('manage_applications')) return null
  const forward = targets.filter((t) => t !== 'REJECTED')
  const canReject = targets.includes('REJECTED')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Move ${name}`}
          disabled={disabled}
          className="shrink-0"
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {extra}
        {extra && <DropdownMenuSeparator />}
        <DropdownMenuLabel>Currently {APPLICATION_STATUS_LABELS[status].toLowerCase()}</DropdownMenuLabel>
        {targets.length === 0 && (
          <DropdownMenuItem disabled>
            <Ban /> No further moves
          </DropdownMenuItem>
        )}
        {forward.map((t) => (
          <DropdownMenuItem key={t} onSelect={() => onMove(t)}>
            <ArrowRight /> {moveLabel(t)}
            <span className="ml-auto text-xs text-muted-foreground">{APPLICATION_STATUS_LABELS[t]}</span>
          </DropdownMenuItem>
        ))}
        {canReject && (
          <>
            {forward.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem destructive onSelect={() => onMove('REJECTED')}>
              <Ban /> Reject…
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
