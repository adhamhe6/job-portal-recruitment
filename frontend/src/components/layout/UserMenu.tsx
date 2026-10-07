import { LogOut, Settings, UserRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Avatar } from '@/components/ui/avatar'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { ROLE_LABELS } from '@/lib/enums'
import { paths } from '@/routes/paths'

export function UserMenu() {
  const { user, logout, isCandidate } = useAuth()
  const navigate = useNavigate()
  if (!user) return null
  const name = `${user.first_name} ${user.last_name}`
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Account menu for ${name}`}
          className="flex cursor-pointer items-center gap-2 rounded-full p-0.5 pr-1 transition-colors hover:bg-accent sm:pr-2.5"
        >
          <Avatar name={name} size="sm" />
          <span className="hidden text-left sm:block">
            <span className="block max-w-32 truncate text-[13px] leading-tight font-medium">{name}</span>
            <span className="block text-[11px] leading-tight text-muted-foreground">{ROLE_LABELS[user.role]}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64">
        <div className="px-2.5 py-2">
          <p className="truncate text-sm font-semibold">{name}</p>
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          {user.company && <p className="mt-0.5 truncate text-xs text-muted-foreground">{user.company.name}</p>}
        </div>
        <DropdownMenuSeparator />
        {isCandidate && (
          <DropdownMenuItem onSelect={() => navigate(paths.profile)}>
            <UserRound /> Profile
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => navigate(paths.settings)}>
          <Settings /> Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          onSelect={async () => {
            await logout()
            navigate(paths.login, { replace: true })
          }}
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
