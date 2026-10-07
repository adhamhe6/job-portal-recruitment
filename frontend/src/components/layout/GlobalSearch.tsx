import { Search } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { paths } from '@/routes/paths'

/**
 * Header search. Candidates / visitors search public jobs; staff and admins search their jobs list.
 * "/" or Ctrl/Cmd+K focuses it from anywhere (unless typing in a field).
 */
export function GlobalSearch() {
  const { isStaff, isAdmin } = useAuth()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const ref = useRef<HTMLInputElement>(null)
  const target = isStaff || isAdmin ? paths.manageJobs : paths.jobs

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
      if (((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') || (e.key === '/' && !typing)) {
        e.preventDefault()
        ref.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const term = q.trim()
    navigate(term ? `${target}?q=${encodeURIComponent(term)}` : target)
    setQ('')
    ref.current?.blur()
  }

  return (
    <>
      <form role="search" onSubmit={submit} className="relative hidden max-w-md flex-1 md:block">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input
          ref={ref}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label={isStaff || isAdmin ? 'Search your jobs' : 'Search jobs'}
          placeholder={isStaff || isAdmin ? 'Search your jobs…' : 'Search jobs, skills, companies…'}
          className="h-9 w-full rounded-lg border border-input bg-surface pr-12 pl-9 text-sm shadow-xs transition-colors placeholder:text-muted-foreground hover:border-ring/40 focus-visible:border-ring focus-visible:bg-card focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-search-cancel-button]:hidden"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2.5 hidden -translate-y-1/2 rounded border bg-card px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground lg:block" aria-hidden>
          Ctrl K
        </kbd>
      </form>
      <Button asChild variant="ghost" size="icon" className="md:hidden">
        <Link to={target} aria-label="Search jobs">
          <Search />
        </Link>
      </Button>
    </>
  )
}
