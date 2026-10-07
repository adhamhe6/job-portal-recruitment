import { Heart } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { loginUrl } from '@/routes/paths'
import { useToggleSaveJob } from '../api/jobs'

/**
 * Heart toggle. Candidates: optimistic save/unsave (PUT/DELETE /jobs/{id}/save).
 * Visitors: a link to sign in (returns here afterwards). Staff/admin: renders nothing.
 */
export function SaveJobButton({
  jobId,
  jobTitle,
  saved,
  variant = 'icon',
  className,
}: {
  jobId: string
  jobTitle: string
  saved: boolean | null | undefined
  variant?: 'icon' | 'button'
  className?: string
}) {
  const { status, isCandidate } = useAuth()
  const location = useLocation()
  const toggle = useToggleSaveJob()

  if (status !== 'authenticated') {
    const to = loginUrl(location.pathname + location.search)
    return variant === 'icon' ? (
      <Tooltip content="Sign in to save jobs">
        <Button asChild variant="ghost" size="icon" className={className}>
          <Link to={to} aria-label={`Sign in to save ${jobTitle}`}>
            <Heart />
          </Link>
        </Button>
      </Tooltip>
    ) : (
      <Button asChild variant="outline" className={className}>
        <Link to={to}>
          <Heart /> Save
        </Link>
      </Button>
    )
  }
  if (!isCandidate) return null

  const isSaved = Boolean(saved)
  const onClick = () =>
    toggle.mutate(
      { jobId, save: !isSaved },
      {
        onSuccess: () => toast.success(isSaved ? 'Removed from saved jobs' : 'Job saved'),
        onError: (e) => toast.error(isSaved ? 'Could not remove the job' : 'Could not save the job', { description: errorMessage(e) }),
      },
    )
  const label = isSaved ? `Remove ${jobTitle} from saved jobs` : `Save ${jobTitle}`
  const icon = <Heart className={cn(isSaved && 'fill-rose-500 text-rose-500')} />

  return variant === 'icon' ? (
    <Tooltip content={isSaved ? 'Saved' : 'Save job'}>
      <Button variant="ghost" size="icon" className={className} aria-label={label} aria-pressed={isSaved} onClick={onClick} disabled={toggle.isPending}>
        {icon}
      </Button>
    </Tooltip>
  ) : (
    <Button variant="outline" className={className} aria-label={label} aria-pressed={isSaved} onClick={onClick} disabled={toggle.isPending}>
      {icon} {isSaved ? 'Saved' : 'Save'}
    </Button>
  )
}
