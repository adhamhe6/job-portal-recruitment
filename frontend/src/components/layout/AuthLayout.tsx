import { CheckCircle2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { Logo } from '@/components/common/Logo'
import { paths } from '@/routes/paths'
import { SkipLink } from './RouteFocus'
import { ThemeToggle } from './ThemeToggle'

const POINTS = [
  'Explainable match scores: see exactly why a job or candidate fits',
  'Résumé parsing that suggests, never silently overwrites, your profile',
  'One pipeline from application to offer, with a full audit trail',
]

/** Split-screen frame for login / registration. The form is rendered via <Outlet/>. */
export function AuthLayout({ children }: { children?: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <SkipLink />
      <aside className="relative hidden overflow-hidden bg-gradient-to-br from-indigo-600 via-indigo-700 to-violet-800 p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div aria-hidden className="absolute -top-24 -right-24 size-96 rounded-full bg-white/10 blur-3xl" />
        <div aria-hidden className="absolute -bottom-32 -left-16 size-96 rounded-full bg-violet-400/20 blur-3xl" />
        <Link to={paths.home} className="relative w-fit rounded-md text-white" aria-label="TalentLens home">
          <Logo />
        </Link>
        <div className="relative max-w-md space-y-6">
          <h2 className="text-4xl leading-tight font-semibold tracking-tight">Hiring, matched with clarity.</h2>
          <ul className="space-y-3 text-indigo-100">
            {POINTS.map((p) => (
              <li key={p} className="flex gap-3 text-[15px]">
                <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-violet-200" aria-hidden />
                {p}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-sm text-indigo-200">© {new Date().getFullYear()} TalentLens</p>
      </aside>
      <div className="flex min-h-dvh flex-col bg-background">
        <div className="flex items-center justify-between px-5 py-4 sm:px-8">
          <Link to={paths.home} className="rounded-md lg:invisible" aria-label="TalentLens home">
            <Logo />
          </Link>
          <ThemeToggle />
        </div>
        <main id="main-content" tabIndex={-1} className="flex flex-1 items-start justify-center px-5 pt-4 pb-12 outline-none sm:px-8 lg:items-center">
          <div className="w-full max-w-md">{children ?? <Outlet />}</div>
        </main>
      </div>
    </div>
  )
}
