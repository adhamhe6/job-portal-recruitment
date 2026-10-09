import { MoreHorizontal, ShieldCheck, UserCheck, UserX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { AdminUser } from '../api/types'

/** Row "⋯" menu. Own account: no menu (the API refuses self-suspension and self role change). */
export function UserRowActions({
  user,
  isSelf,
  onChangeRole,
  onToggleStatus,
}: {
  user: AdminUser
  isSelf: boolean
  onChangeRole: (u: AdminUser) => void
  onToggleStatus: (u: AdminUser) => void
}) {
  const name = `${user.first_name} ${user.last_name}`
  if (isSelf) return <span className="text-xs text-muted-foreground">You</span>
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-52">
        <DropdownMenuItem onSelect={() => onChangeRole(user)}>
          <ShieldCheck /> Change role…
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {user.status === 'ACTIVE' ? (
          <DropdownMenuItem destructive onSelect={() => onToggleStatus(user)}>
            <UserX /> Deactivate…
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={() => onToggleStatus(user)}>
            <UserCheck /> Reactivate…
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
