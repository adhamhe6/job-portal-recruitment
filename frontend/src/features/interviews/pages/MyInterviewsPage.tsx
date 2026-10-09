import { CalendarX } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState, ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ApiError, errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import {
  useConfirmInterview,
  useMyInterviews,
  type CandidateInterview,
  type InterviewView,
} from '../api/myInterviews'
import { MyInterviewCard } from '../components/MyInterviewCard'

const VIEWS: { value: InterviewView; label: string }[] = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'past', label: 'Past' },
  { value: 'all', label: 'All' },
]

const EMPTY: Record<InterviewView, { title: string; description: string }> = {
  upcoming: {
    title: 'No upcoming interviews',
    description:
      'When a hiring team schedules an interview with you, it shows up here and you get a notification.',
  },
  past: {
    title: 'No past interviews yet',
    description: 'Completed, cancelled and missed interviews will be listed here.',
  },
  all: {
    title: 'No interviews yet',
    description: 'Apply to jobs and, when you are shortlisted, interview invitations will appear here.',
  },
}

function confirmError(e: unknown): string {
  if (e instanceof ApiError && e.status === 409)
    return 'This interview can no longer be confirmed — its status changed. Refresh to see the latest.'
  return errorMessage(e)
}

export default function MyInterviewsPage() {
  useDocumentTitle('My interviews')
  const [{ view, page }, update] = useUrlState({ view: 'upcoming', page: 1 })
  const current: InterviewView = view === 'past' || view === 'all' ? view : 'upcoming'
  const query = useMyInterviews({ view: current, page })
  const confirm = useConfirmInterview()
  const [confirmingId, setConfirmingId] = useState<string | null>(null)

  const onConfirm = async (i: CandidateInterview) => {
    setConfirmingId(i.id)
    try {
      await confirm.mutateAsync(i.id)
      toast.success('Attendance confirmed', { description: `${i.job_title} · ${i.company_name}` })
    } catch (e) {
      toast.error('Could not confirm the interview', { description: confirmError(e) })
    } finally {
      setConfirmingId(null)
    }
  }

  return (
    <>
      <PageHeader
        title="My interviews"
        description="Times are shown in your local time zone. Confirm each interview so the team knows you'll be there."
        actions={
          <Button asChild variant="outline">
            <Link to={paths.applications}>My applications</Link>
          </Button>
        }
      />

      <Tabs value={current} onValueChange={(v) => update({ view: v })}>
        <TabsList aria-label="Interview filter">
          {VIEWS.map((v) => (
            <TabsTrigger key={v.value} value={v.value}>
              {v.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div
        className="mt-4"
        role="region"
        aria-label={`${VIEWS.find((v) => v.value === current)?.label} interviews`}
      >
        {query.isPending ? (
          <div className="grid gap-3" role="status" aria-busy="true" aria-label="Loading interviews">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-44 w-full rounded-xl" />
            ))}
          </div>
        ) : query.isError && !query.data ? (
          <ErrorState
            error={query.error}
            onRetry={() => query.refetch()}
            title="Couldn't load your interviews"
          />
        ) : query.data && query.data.items.length === 0 ? (
          <div className="rounded-xl border border-dashed">
            <EmptyState
              icon={<CalendarX aria-hidden />}
              title={EMPTY[current].title}
              description={EMPTY[current].description}
              action={
                <Button asChild variant="outline">
                  <Link to={paths.applications}>View my applications</Link>
                </Button>
              }
            />
          </div>
        ) : query.data ? (
          <div className={cn(query.isPlaceholderData && 'opacity-70 transition-opacity')}>
            <ul
              className="grid gap-3"
              aria-label="Interviews"
              aria-busy={query.isPlaceholderData || undefined}
            >
              {query.data.items.map((i) => (
                <MyInterviewCard
                  key={i.id}
                  interview={i}
                  confirming={confirmingId === i.id}
                  onConfirm={onConfirm}
                />
              ))}
            </ul>
            <Pagination
              page={query.data.page}
              pages={query.data.pages}
              total={query.data.total}
              pageSize={query.data.page_size}
              onPageChange={(p) => update({ page: p }, { resetPage: false })}
              label="interviews"
            />
          </div>
        ) : null}
      </div>
    </>
  )
}
