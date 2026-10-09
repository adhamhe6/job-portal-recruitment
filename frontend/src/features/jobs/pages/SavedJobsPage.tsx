import { Heart } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { paths } from '@/routes/paths'
import { useSavedJobs } from '../api/jobs'
import { JobResults } from '../components/JobResults'
import { JobsTabs } from '../components/JobsTabs'

export default function SavedJobsPage() {
  useDocumentTitle('Saved jobs')
  const [{ page }, update] = useUrlState({ page: 1 })
  const query = useSavedJobs(page)
  return (
    <>
      <PageHeader title="Find jobs" description="Jobs you saved to come back to." />
      <JobsTabs />
      <JobResults
        query={query}
        label="saved jobs"
        onPageChange={(p) => update({ page: p }, { resetPage: false })}
        empty={
          <EmptyState
            icon={<Heart aria-hidden />}
            title="No saved jobs yet"
            description="Tap the heart on any job to keep it here for later."
            action={
              <Button asChild>
                <Link to={paths.jobs}>Browse jobs</Link>
              </Button>
            }
          />
        }
      />
    </>
  )
}
