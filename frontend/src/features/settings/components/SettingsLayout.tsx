import { Building2, UserRound, Users } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'

/**
 * Frame for /settings/*: a section nav + the section page (<Outlet/>).
 * Wave-2 section pages (company, team) render inside this frame and only supply their content.
 */
export function SettingsLayout() {
  const { can, user } = useAuth()
  useDocumentTitle('Settings')
  const sections = [
    { to: paths.settings, label: 'Account', icon: UserRound, end: true, show: true },
    { to: paths.settingsCompany, label: 'Company', icon: Building2, end: false, show: can('manage_own_company') },
    { to: paths.settingsTeam, label: 'Team', icon: Users, end: false, show: can('manage_own_company') && Boolean(user?.is_company_admin) },
  ].filter((s) => s.show)

  return (
    <>
      <PageHeader title="Settings" description="Manage your account and preferences." />
      <div className="grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="flex gap-1 overflow-x-auto lg:flex-col">
          {sections.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex h-10 shrink-0 items-center gap-2.5 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
                  isActive && 'bg-accent text-accent-foreground',
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </>
  )
}
