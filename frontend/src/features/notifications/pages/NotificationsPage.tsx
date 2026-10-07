import { BellOff, CheckCheck } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Pagination } from '@/components/ui/pagination'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { paths } from '@/routes/paths'
import { Link } from 'react-router-dom'
import { useMarkAllRead, useMarkRead, useNotifications, useUnreadCount } from '../api/notifications'
import { NotificationItem } from '../components/NotificationItem'

const PAGE_SIZE = 15

export default function NotificationsPage() {
  useDocumentTitle('Notifications')
  const [{ filter, page }, update] = useUrlState({ filter: 'all', page: 1 })
  const unreadOnly = filter === 'unread'
  const list = useNotifications({ page, pageSize: PAGE_SIZE, unreadOnly })
  const unread = useUnreadCount()
  const markRead = useMarkRead()
  const markAll = useMarkAllRead()

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Updates about your applications, interviews, résumés and matches."
        actions={
          <Button variant="outline" onClick={() => markAll.mutate()} disabled={(unread.data ?? 0) === 0} loading={markAll.isPending}>
            <CheckCheck /> Mark all as read
          </Button>
        }
      />
      <Tabs value={unreadOnly ? 'unread' : 'all'} onValueChange={(v) => update({ filter: v })} className="mb-4">
        <TabsList aria-label="Filter notifications">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="unread">
            Unread
            {(unread.data ?? 0) > 0 && (
              <span className="rounded-full bg-primary px-1.5 text-[11px] leading-5 font-semibold text-primary-foreground tabular">{unread.data}</span>
            )}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <Card className="overflow-hidden">
        {list.isPending ? (
          <TableSkeleton rows={6} cols={3} />
        ) : list.isError ? (
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState
            icon={<BellOff aria-hidden />}
            title={unreadOnly ? "You're all caught up" : 'No notifications yet'}
            description={
              unreadOnly ? 'There is nothing unread.' : 'When something happens with your applications, interviews or matches, you will see it here.'
            }
            action={
              unreadOnly ? (
                <Button variant="outline" onClick={() => update({ filter: 'all' })}>
                  Show all notifications
                </Button>
              ) : (
                <Button asChild>
                  <Link to={paths.jobs}>Browse jobs</Link>
                </Button>
              )
            }
          />
        ) : (
          <ul className="divide-y" aria-label="Notifications" aria-busy={list.isFetching}>
            {list.data.items.map((n) => (
              <li key={n.id}>
                <NotificationItem notification={n} onOpen={(x) => !x.is_read && markRead.mutate(x.id)} />
              </li>
            ))}
          </ul>
        )}
      </Card>
      {list.data && list.data.pages > 1 && (
        <Pagination page={list.data.page} pages={list.data.pages} total={list.data.total} pageSize={list.data.page_size} onPageChange={(p) => update({ page: p }, { resetPage: false })} label="notifications" />
      )}
    </>
  )
}
