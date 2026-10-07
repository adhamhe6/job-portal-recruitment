import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { Logo, LogoMark } from '@/components/common/Logo'
import { Tooltip } from '@/components/ui/tooltip'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useUnreadCount } from '@/features/notifications/api/notifications'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { navItemsFor, type NavItem } from './nav'

function NavEntry({ item, collapsed, unread, onNavigate }: { item: NavItem; collapsed: boolean; unread: number; onNavigate?: () => void }) {
  const Icon = item.icon
  const showBadge = item.badge === 'notifications' && unread > 0
  const link = (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      aria-label={collapsed ? `${item.label}${showBadge ? `, ${unread} unread` : ''}` : undefined}
      className={({ isActive }) =>
        cn(
          'group relative flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium text-sidebar-foreground transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground',
          isActive && 'bg-sidebar-accent text-sidebar-accent-foreground before:absolute before:top-2 before:bottom-2 before:-left-3 before:w-1 before:rounded-r-full before:bg-primary',
          collapsed && 'justify-center px-0',
        )
      }
    >
      <Icon className="size-[18px] shrink-0" aria-hidden />
      {!collapsed && <span className="truncate">{item.label}</span>}
      {showBadge && !collapsed && (
        <span className="ml-auto rounded-full bg-primary px-1.5 text-[11px] leading-5 font-semibold text-primary-foreground tabular">{unread > 99 ? '99+' : unread}</span>
      )}
      {showBadge && collapsed && <span className="absolute top-2 right-2.5 size-2 rounded-full bg-primary ring-2 ring-sidebar" aria-hidden />}
    </NavLink>
  )
  return collapsed ? (
    <Tooltip content={item.label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  )
}

/** Role-specific navigation. `collapsed` = icon rail (desktop). In the mobile sheet it is always expanded. */
export function Sidebar({ collapsed = false, onToggle, onNavigate }: { collapsed?: boolean; onToggle?: () => void; onNavigate?: () => void }) {
  const { user } = useAuth()
  const unread = useUnreadCount().data ?? 0
  const items = navItemsFor(user?.role)
  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className={cn('flex h-16 shrink-0 items-center border-b border-sidebar-border px-4', collapsed && 'justify-center px-0')}>
        <Link to={paths.dashboard} onClick={onNavigate} aria-label="TalentLens home" className="rounded-md">
          {collapsed ? <LogoMark /> : <Logo />}
        </Link>
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={item.to + item.label}>
              <NavEntry item={item} collapsed={collapsed} unread={unread} onNavigate={onNavigate} />
            </li>
          ))}
        </ul>
      </nav>
      {onToggle && (
        <div className={cn('shrink-0 border-t border-sidebar-border p-3', collapsed && 'flex justify-center')}>
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className={cn(
              'flex h-9 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm text-sidebar-foreground transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground',
              collapsed && 'w-9 justify-center px-0',
            )}
          >
            {collapsed ? <PanelLeftOpen className="size-[18px]" aria-hidden /> : <PanelLeftClose className="size-[18px]" aria-hidden />}
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      )}
    </div>
  )
}
