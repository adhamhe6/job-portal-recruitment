import { Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Field } from '@/components/ui/field'
import { NativeSelect } from '@/components/ui/input'
import { MatchDetailPanel } from '@/features/matching/components/MatchDetailPanel'
import { Button } from '@/components/ui/button'
import { paths } from '@/routes/paths'
import { Section } from './ProfileSections'
import { useJobOptions } from '../hooks/useJobOptions'

/** "How does this candidate fit job X": job picker (kept in the URL by the page) + the explained match. */
export function CandidateMatchPanel({
  candidateId,
  jobId,
  onJobChange,
  applicationJobIds,
}: {
  candidateId: string
  jobId: string
  onJobChange: (jobId: string) => void
  /** Jobs this candidate applied to; listed first. */
  applicationJobIds: string[]
}) {
  const jobs = useJobOptions()
  const applied = new Set(applicationJobIds)
  const sorted = [...jobs.options].sort((a, b) => Number(applied.has(b.value)) - Number(applied.has(a.value)))
  return (
    <Section title="Match with a job" icon={<Sparkles aria-hidden />}>
      <div className="space-y-4">
        <Field
          label="Job"
          hint="Jobs this candidate applied to are listed first."
          error={jobs.isError ? 'Your jobs could not be loaded.' : null}
        >
          <NativeSelect value={jobId} onChange={(e) => onJobChange(e.target.value)} disabled={jobs.isPending}>
            <option value="">{jobs.isPending ? 'Loading jobs…' : 'Choose a job'}</option>
            {jobId && !sorted.some((o) => o.value === jobId) && <option value={jobId}>Selected job</option>}
            {sorted.map((o) => (
              <option key={o.value} value={o.value}>
                {applied.has(o.value) ? `${o.label} (applied)` : o.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {jobId ? (
          <>
            <MatchDetailPanel jobId={jobId} candidateId={candidateId} />
            <Button asChild variant="outline" size="sm">
              <Link to={paths.matchingJob(jobId)}>See where they rank for this job</Link>
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            Choose one of your company’s jobs to see a ranked, explained match for this candidate.
          </p>
        )}
      </div>
    </Section>
  )
}
