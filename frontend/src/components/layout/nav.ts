import {
  Activity,
  BarChart3,
  Bell,
  Briefcase,
  Building2,
  CalendarDays,
  ClipboardList,
  FileUser,
  LayoutDashboard,
  Search,
  Settings,
  Sparkles,
  Target,
  UserRound,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'
import type { Role } from '@/lib/api'
import { paths } from '@/routes/paths'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  /** Match only the exact path (for index-like routes). */
  end?: boolean
  /** Shows the unread-notifications badge. */
  badge?: 'notifications'
}

const dashboard: NavItem = { label: 'Dashboard', to: paths.dashboard, icon: LayoutDashboard }
const notifications: NavItem = { label: 'Notifications', to: paths.notifications, icon: Bell, badge: 'notifications' }
const settings: NavItem = { label: 'Settings', to: paths.settings, icon: Settings }

/** Role-specific sidebar navigation (per the product spec). Add a page to the route table first, then list it here. */
export const NAV_BY_ROLE: Record<Role, NavItem[]> = {
  CANDIDATE: [
    dashboard,
    { label: 'Find Jobs', to: paths.jobs, icon: Search },
    { label: 'Recommended Jobs', to: paths.recommended, icon: Sparkles },
    { label: 'Applications', to: paths.applications, icon: ClipboardList },
    { label: 'Interviews', to: paths.interviews, icon: CalendarDays },
    { label: 'Résumé', to: paths.resume, icon: FileUser },
    { label: 'Profile', to: paths.profile, icon: UserRound },
    notifications,
    settings,
  ],
  RECRUITER: [
    dashboard,
    { label: 'Jobs', to: paths.manageJobs, icon: Briefcase },
    { label: 'Candidates', to: paths.candidates, icon: Users },
    { label: 'Applications', to: paths.applications, icon: ClipboardList },
    { label: 'Interviews', to: paths.interviews, icon: CalendarDays },
    { label: 'Candidate Matching', to: paths.matching, icon: Target },
    { label: 'Reports', to: paths.reports, icon: BarChart3 },
    notifications,
    settings,
  ],
  HIRING_MANAGER: [
    dashboard,
    { label: 'Jobs', to: paths.manageJobs, icon: Briefcase },
    { label: 'Applications', to: paths.applications, icon: ClipboardList },
    { label: 'Interviews', to: paths.interviews, icon: CalendarDays },
    { label: 'Candidate Matching', to: paths.matching, icon: Target },
    notifications,
    settings,
  ],
  ADMIN: [
    dashboard,
    { label: 'Users', to: paths.adminUsers, icon: UsersRound },
    { label: 'Companies', to: paths.adminCompanies, icon: Building2 },
    { label: 'Jobs', to: paths.manageJobs, icon: Briefcase },
    { label: 'Applications', to: paths.applications, icon: ClipboardList },
    { label: 'System Monitoring', to: paths.adminSystem, icon: Activity },
    { label: 'Reports', to: paths.reports, icon: BarChart3 },
    settings,
  ],
}

export function navItemsFor(role: Role | undefined | null): NavItem[] {
  return role ? NAV_BY_ROLE[role] : []
}
