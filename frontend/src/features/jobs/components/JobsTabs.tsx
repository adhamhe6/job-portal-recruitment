import { Heart, Search } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'

/** "All jobs | Saved" switcher shown to candidates above the search and saved lists. */
export function JobsTabs() {
  const { isCandidate } = useAuth()
  if (!isCandidate) return null
  const cls = ({ isActive }: { isActive: boolean }) =>
    cn(
      'inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground [&_svg]:size-4',
      isActive && 'bg-card text-foreground shadow-sm',
    )
  return (
    <nav aria-label="Job lists" className="mb-5 inline-flex gap-1 rounded-xl bg-muted p-1">
      <NavLink to={paths.jobs} end className={cls}>
        <Search aria-hidden /> All jobs
      </NavLink>
      <NavLink to={paths.jobsSaved} className={cls}>
        <Heart aria-hidden /> Saved
      </NavLink>
    </nav>
  )
}
