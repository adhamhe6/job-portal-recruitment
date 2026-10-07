import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { paths } from '@/routes/paths'
import { useMarkAllRead, useMarkRead, useNotifications, useUnreadCount } from '../api/notifications'
import { NotificationItem } from './NotificationItem'

/** Header bell: unread badge (polled) + dropdown with the latest notifications. */
export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const unread = useUnreadCount()
  const list = useNotifications({ pageSize: 8, enabled: open })
  const markRead = useMarkRead()
  const markAll = useMarkAllRead()
  const count = unread.data ?? 0
  const label = count > 0 ? `Notifications, ${count} unread` : 'Notifications'

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={label} className="relative">
          <Bell />
          {count > 0 && (
            <span
              data-testid="unread-badge"
              aria-hidden
              className="absolute top-1 right-1 flex min-w-4.5 items-center justify-center rounded-full bg-destructive px-1 text-[10px] leading-4.5 font-bold text-destructive-foreground ring-2 ring-background"
            >
              {count > 99 ? '99+' : count}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[26rem]" align="end">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Notifications</h2>
          <Button variant="ghost" size="sm" disabled={count === 0 || markAll.isPending} onClick={() => markAll.mutate()}>
            <CheckCheck /> Mark all read
          </Button>
        </div>
        <div className="max-h-[min(26rem,60dvh)] overflow-y-auto">
          {list.isPending ? (
            <div className="space-y-3 p-4" role="status" aria-label="Loading notifications">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex gap-3">
                  <Skeleton className="size-9 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-3 w-full" />
                  </div>
                </div>
              ))}
            </div>
          ) : list.isError ? (
            <ErrorState error={list.error} onRetry={() => list.refetch()} compact />
          ) : list.data.items.length === 0 ? (
            <EmptyState compact title="You're all caught up" description="New updates about applications, interviews and matches will show up here." />
          ) : (
            <ul className="divide-y">
              {list.data.items.map((n) => (
                <li key={n.id}>
                  <NotificationItem
                    dense
                    notification={n}
                    onOpen={(x) => {
                      if (!x.is_read) markRead.mutate(x.id)
                      setOpen(false)
                    }}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="border-t p-2">
          <Button asChild variant="ghost" size="sm" className="w-full" onClick={() => setOpen(false)}>
            <Link to={paths.notifications}>View all notifications</Link>
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
