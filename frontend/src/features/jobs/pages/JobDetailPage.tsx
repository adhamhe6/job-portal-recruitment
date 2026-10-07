import { Building2, CalendarClock, ExternalLink, GraduationCap, MapPin, Timer, Wallet } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CopyButton } from '@/components/common/CopyButton'
import { PageHeader } from '@/components/common/PageHeader'
import { SkillChip } from '@/components/common/SkillChip'
import { ErrorState } from '@/components/common/States'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TextBlock } from '@/components/common/TextBlock'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useMyJobMatch } from '@/features/matches/api/matches'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import type { JobPublic } from '@/lib/api'
import { ApiError } from '@/lib/api'
import { EDUCATION_LEVEL_LABELS, EXPERIENCE_LEVEL_LABELS } from '@/lib/enums'
import { dates, deadlineHint, formatExperienceRange, formatSalaryRange } from '@/lib/format'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { isStaffView, useJob, useJobStats, type JobView } from '../api/jobs'
import { ApplyCta } from '../components/ApplyCta'
import { CompanyLogo } from '../components/CompanyLogo'
import { JobBadges } from '../components/JobBadges'
import { JobOverview } from '../components/JobOverview'
import { MatchCard } from '../components/MatchCard'
import { SaveJobButton } from '../components/SaveJobButton'
import { StaffJobPanel } from '../components/StaffJobPanel'

function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="text-sm font-medium break-words">{children}</dd>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  )
}

function JobSkills({ job, matched }: { job: JobView; matched: Set<string> }) {
  const required = job.skills.filter((s) => s.requirement === 'REQUIRED')
  const preferred = job.skills.filter((s) => s.requirement === 'PREFERRED')
  if (required.length + preferred.length === 0) return null
  const chip = (s: JobView['skills'][number], tone: 'required' | 'preferred') => {
    const have = matched.has(s.skill.name.toLowerCase())
    const years = s.min_years && Number(s.min_years) > 0 ? ` · ${Number(s.min_years)}+ yrs` : ''
    return (
      <SkillChip
        name={`${s.skill.name}${years}`}
        tone={have ? 'matched' : tone}
        prefix={have ? <span aria-label="You have this skill">✓</span> : undefined}
      />
    )
  }
  return (
    <Section title="Skills">
      {required.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground">Required</h3>
          <ul className="flex flex-wrap gap-2">
            {required.map((s) => (
              <li key={s.skill.id}>{chip(s, 'required')}</li>
            ))}
          </ul>
        </div>
      )}
      {preferred.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground">Nice to have</h3>
          <ul className="flex flex-wrap gap-2">
            {preferred.map((s) => (
              <li key={s.skill.id}>{chip(s, 'preferred')}</li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  )
}

function CompanyCard({ company }: { company: JobPublic['company'] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3 space-y-0">
        <CompanyLogo name={company.name} logoUrl={company.logo_url} size="md" />
        <div className="min-w-0">
          <CardTitle className="truncate">{company.name}</CardTitle>
          <p className="truncate text-sm text-muted-foreground">
            {[company.industry, company.size && `${company.size} employees`].filter(Boolean).join(' · ')}
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {company.description && (
          <p className="line-clamp-5 text-sm text-muted-foreground">{company.description}</p>
        )}
        {company.location && (
          <p className="flex items-center gap-2 text-sm">
            <MapPin className="size-4 text-muted-foreground" aria-hidden /> {company.location}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to={`${paths.jobs}?company_id=${company.id}`}>More jobs here</Link>
          </Button>
          {company.website && /^https?:\/\//i.test(company.website) && (
            <Button asChild variant="ghost" size="sm">
              <a href={company.website} target="_blank" rel="noopener noreferrer">
                Website <ExternalLink />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-busy="true" aria-label="Loading job">
      <Skeleton className="h-4 w-48" />
      <div className="flex gap-4">
        <Skeleton className="size-20 rounded-xl" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-6 w-1/2" />
        </div>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Skeleton className="h-96 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  )
}

export default function JobDetailPage() {
  const { id } = useParams()
  const { isCandidate, status } = useAuth()
  const isLg = useMediaQuery('(min-width: 1024px)', true)
  const job = useJob(id)
  // Kicked off in parallel with the job request (same query keys as the cards below), so the page has no request waterfall.
  const match = useMyJobMatch(id)
  useJobStats(id)
  useDocumentTitle(job.data ? `${job.data.title} at ${job.data.company.name}` : 'Job')

  if (job.isPending) return <DetailSkeleton />
  if (job.isError) {
    const notFound = job.error instanceof ApiError && job.error.status === 404
    return (
      <div className="mx-auto max-w-xl py-8">
        <ErrorState
          error={job.error}
          onRetry={notFound ? undefined : () => job.refetch()}
          title={notFound ? 'This job isn’t available' : undefined}
        />
        {notFound && (
          <div className="-mt-6 text-center">
            <p className="mx-auto mb-4 max-w-md text-sm text-muted-foreground">
              It may have been closed, paused or removed by the employer — or you may not have access to it.
            </p>
            <Button asChild>
              <Link to={paths.jobs}>Browse open jobs</Link>
            </Button>
          </div>
        )}
      </div>
    )
  }

  const j = job.data
  const staff = isStaffView(j)
  const salary = formatSalaryRange(j.salary_min, j.salary_max, j.salary_currency, false)
  const deadline = deadlineHint(j.application_deadline)
  const matchedNames = new Set((match.data?.matched_skills ?? []).map((s) => s.toLowerCase()))
  const showCandidateCta = status !== 'authenticated' || isCandidate
  const url = typeof window !== 'undefined' ? window.location.href : ''

  return (
    <div className={cn(showCandidateCta && !isLg && 'pb-24')}>
      <PageHeader
        breadcrumbs={[{ label: 'Jobs', to: staff ? paths.manageJobs : paths.jobs }, { label: j.title }]}
        title={
          <span className="flex items-start gap-4">
            <CompanyLogo
              name={j.company.name}
              logoUrl={j.company.logo_url}
              size="xl"
              className="hidden sm:inline-flex"
            />
            <span className="min-w-0">
              <span className="block">{j.title}</span>
              <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-base font-normal text-muted-foreground">
                <Link
                  to={`${paths.jobs}?company_id=${j.company.id}`}
                  className="font-medium text-foreground/80 hover:text-primary hover:underline"
                >
                  {j.company.name}
                </Link>
                {j.location && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="size-4" aria-hidden /> {j.location}
                  </span>
                )}
                {j.published_at && <span className="text-sm">Posted {dates.relative(j.published_at)}</span>}
              </span>
            </span>
          </span>
        }
        meta={
          <>
            <JobBadges
              workplace={j.workplace_type}
              employment={j.employment_type}
              level={j.experience_level}
            />
            {staff && <StatusBadge kind="job" status={j.status} />}
            {j.is_saved && <Badge variant="muted">Saved</Badge>}
          </>
        }
        actions={
          <>
            <CopyButton value={url} label="Copy link to this job" size="icon" />
            {isLg && <SaveJobButton jobId={j.id} jobTitle={j.title} saved={j.is_saved} variant="button" />}
          </>
        }
      />

      {staff && (
        <div className="mb-6 space-y-6">
          <StaffJobPanel job={j} />
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-8">
          <Card>
            <CardContent className="space-y-8 p-5 pt-5 sm:p-7 sm:pt-7">
              <Section title="About the role">
                <TextBlock text={j.description} />
              </Section>
              {j.responsibilities && (
                <Section title="Responsibilities">
                  <TextBlock text={j.responsibilities} />
                </Section>
              )}
              {j.qualifications && (
                <Section title="Qualifications">
                  <TextBlock text={j.qualifications} />
                </Section>
              )}
              <JobSkills job={j} matched={matchedNames} />
              {j.benefits && (
                <Section title="Benefits">
                  <TextBlock text={j.benefits} />
                </Section>
              )}
            </CardContent>
          </Card>
          {staff && <JobOverview jobId={j.id} />}
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24" aria-label="Job summary">
          {showCandidateCta && isLg && (
            <Card>
              <CardContent className="space-y-3 p-5">
                <ApplyCta job={j} />
                {deadline && j.can_apply !== false && (
                  <p
                    className={cn(
                      'text-center text-sm',
                      deadline.tone === 'urgent'
                        ? 'font-medium text-amber-700 dark:text-amber-400'
                        : 'text-muted-foreground',
                    )}
                  >
                    {deadline.text}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Job details</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-4">
                {salary && (
                  <Fact icon={<Wallet />} label="Salary (yearly)">
                    {salary}
                  </Fact>
                )}
                <Fact icon={<Timer />} label="Experience">
                  {formatExperienceRange(j.min_experience_years, j.max_experience_years)}
                  {j.experience_level && (
                    <span className="font-normal text-muted-foreground">
                      {' '}
                      · {EXPERIENCE_LEVEL_LABELS[j.experience_level]}
                    </span>
                  )}
                </Fact>
                {j.min_education_level && (
                  <Fact icon={<GraduationCap />} label="Education">
                    {EDUCATION_LEVEL_LABELS[j.min_education_level]} or equivalent
                  </Fact>
                )}
                {j.department && (
                  <Fact icon={<Building2 />} label="Department">
                    {j.department}
                  </Fact>
                )}
                <Fact icon={<CalendarClock />} label="Application deadline">
                  {j.application_deadline ? (
                    <>
                      {dates.date(j.application_deadline)}
                      {deadline && deadline.tone !== 'normal' && (
                        <span
                          className={cn(
                            'block text-xs font-normal',
                            deadline.tone === 'past'
                              ? 'text-destructive'
                              : 'text-amber-700 dark:text-amber-400',
                          )}
                        >
                          {deadline.text}
                        </span>
                      )}
                    </>
                  ) : (
                    'Open until filled'
                  )}
                </Fact>
              </dl>
            </CardContent>
          </Card>

          {isCandidate && <MatchCard jobId={j.id} />}
          <CompanyCard company={j.company} />
        </aside>
      </div>

      {showCandidateCta && !isLg && (
        <div className="fixed inset-x-0 bottom-0 z-30 flex items-center gap-2 border-t bg-background/95 p-3 backdrop-blur">
          <div className="min-w-0 flex-1">
            <ApplyCta job={j} compact />
          </div>
          <SaveJobButton jobId={j.id} jobTitle={j.title} saved={j.is_saved} />
        </div>
      )}
    </div>
  )
}
