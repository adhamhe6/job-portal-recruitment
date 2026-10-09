import {
  Briefcase,
  Clock,
  ExternalLink,
  Code2,
  Globe,
  Laptop,
  Link2,
  Mail,
  MapPin,
  Phone,
  ShieldAlert,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { StatusBadge } from '@/components/common/StatusBadge'
import { PageHeader } from '@/components/common/PageHeader'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { ApiError } from '@/lib/api'
import { EMPLOYMENT_TYPE_LABELS } from '@/lib/enums'
import { dates, fmt } from '@/lib/format'
import { paths } from '@/routes/paths'
import { useCandidate, type CandidateView } from '../api/candidates'
import { CandidateMatchPanel } from '../components/CandidateMatchPanel'
import {
  CertificationsSection,
  EducationSection,
  ExperienceSection,
  LanguagesSection,
  Section,
  SkillsSection,
  SummarySection,
} from '../components/ProfileSections'
import { ResumeDownloads } from '../components/ResumeDownloads'
import { AVAILABILITY_LABELS, REMOTE_PREFERENCE_LABELS } from '../lib/filters'
import { preferredResume } from '../lib/profile'

function Fact({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="font-medium break-words">{children}</dd>
      </div>
    </div>
  )
}

function ExternalLinkItem({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <li>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 text-sm font-medium hover:text-primary hover:underline [&_svg]:size-4"
      >
        {icon} {label}
        <ExternalLink className="size-3 text-muted-foreground" aria-hidden />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    </li>
  )
}

function Sidebar({ c }: { c: CandidateView }) {
  const full = c.access === 'FULL'
  const availability = c.availability ? AVAILABILITY_LABELS[c.availability] : null
  const remote = c.remote_preference ? REMOTE_PREFERENCE_LABELS[c.remote_preference] : null
  const employment = c.employment_preference ? EMPLOYMENT_TYPE_LABELS[c.employment_preference] : null
  const links: { href: string; icon: React.ReactNode; label: string }[] = []
  if (c.linkedin_url) links.push({ href: c.linkedin_url, icon: <Link2 aria-hidden />, label: 'LinkedIn' })
  if (c.github_url) links.push({ href: c.github_url, icon: <Code2 aria-hidden />, label: 'GitHub' })
  if (c.portfolio_url) links.push({ href: c.portfolio_url, icon: <Globe aria-hidden />, label: 'Portfolio' })

  return (
    <div className="space-y-6">
      <Section title="Profile at a glance">
        <dl className="space-y-3">
          {c.location && (
            <Fact icon={<MapPin />} label="Location">
              {c.location}
            </Fact>
          )}
          {c.years_experience != null && (
            <Fact icon={<Briefcase />} label="Experience">
              {fmt.num(c.years_experience)} years
            </Fact>
          )}
          {availability && (
            <Fact icon={<Clock />} label="Availability">
              {availability}
            </Fact>
          )}
          {(remote || employment) && (
            <Fact icon={<Laptop />} label="Work preference">
              {[remote, employment].filter(Boolean).join(' · ')}
            </Fact>
          )}
          {c.expected_salary != null && (
            <Fact
              icon={<span className="text-sm font-semibold">{c.salary_currency}</span>}
              label="Expected salary"
            >
              {fmt.money(c.expected_salary, c.salary_currency)} / year
            </Fact>
          )}
        </dl>
        {links.length > 0 && (
          <ul className="mt-4 space-y-2 border-t pt-4" aria-label="Profile links">
            {links.map((l) => (
              <ExternalLinkItem key={l.label} {...l} />
            ))}
          </ul>
        )}
      </Section>

      <Section title="Contact">
        {full ? (
          <dl className="space-y-3">
            {c.email ? (
              <Fact icon={<Mail />} label="E-mail">
                <a href={`mailto:${c.email}`} className="hover:text-primary hover:underline">
                  {c.email}
                </a>
              </Fact>
            ) : null}
            {c.phone ? (
              <Fact icon={<Phone />} label="Phone">
                {c.phone}
              </Fact>
            ) : null}
            {!c.email && !c.phone && (
              <p className="text-sm text-muted-foreground">No contact details on file.</p>
            )}
          </dl>
        ) : (
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            Contact details are only released for people who applied to your jobs or whom your company
            imported. This is a marketplace profile.
          </p>
        )}
      </Section>

      {full && (
        <Section title="Résumés">
          {c.resumes && c.resumes.length > 0 ? (
            <ResumeDownloads resumes={c.resumes} candidateName={c.display_name} />
          ) : (
            <p className="text-sm text-muted-foreground">No résumé on file.</p>
          )}
        </Section>
      )}

      <Section title="Applications to your jobs">
        {c.applications && c.applications.length > 0 ? (
          <ul className="space-y-2.5" aria-label="Applications">
            {c.applications.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <div className="min-w-0">
                  <Link
                    to={paths.application(a.id)}
                    className="font-medium hover:text-primary hover:underline"
                  >
                    {a.job_title}
                  </Link>
                  <p className="text-xs text-muted-foreground">Applied {dates.date(a.applied_at)}</p>
                </div>
                <StatusBadge kind="application" status={a.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">This candidate has not applied to any of your jobs.</p>
        )}
      </Section>
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-busy="true" aria-label="Loading candidate">
      <Skeleton className="h-8 w-1/3" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Skeleton className="h-40 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
        </div>
        <div className="space-y-6">
          <Skeleton className="h-48 rounded-xl" />
          <Skeleton className="h-32 rounded-xl" />
        </div>
      </div>
    </div>
  )
}

export default function CandidateDetailPage() {
  const { id } = useParams()
  const [{ job_id: urlJobId }, update] = useUrlState({ job_id: '' })
  const query = useCandidate(id)
  const c = query.data
  useDocumentTitle(c ? c.display_name : 'Candidate')

  if (query.isPending) return <DetailSkeleton />

  if (query.isError || !c) {
    const status = query.error instanceof ApiError ? query.error.status : 0
    const crumbs = [{ label: 'Candidates', to: paths.candidates }, { label: 'Candidate' }]
    return (
      <>
        <PageHeader breadcrumbs={crumbs} title="Candidate" />
        {status === 404 ? (
          <ErrorState
            error={query.error}
            title="Candidate not found"
            // Never reveal whether the person exists: same message for "unknown" and "not visible to your company".
          />
        ) : (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        )}
        {status === 404 && (
          <p className="mx-auto max-w-md text-center text-sm text-muted-foreground">
            You can only open candidates who applied to your company’s jobs, opted in to the talent
            marketplace, or were imported by your company.
          </p>
        )}
        <div className="mt-4 flex justify-center">
          <Button asChild variant="outline">
            <Link to={paths.candidates}>Back to candidates</Link>
          </Button>
        </div>
      </>
    )
  }

  // Default the match panel to the job they applied to most recently (the API lists applications newest first).
  const applicationJobIds = (c.applications ?? []).map((a) => a.job_id)
  const jobId = urlJobId || applicationJobIds[0] || ''
  const hasResume = c.access === 'FULL' && Boolean(preferredResume(c.resumes ?? []))

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: 'Candidates', to: paths.candidates }, { label: c.display_name }]}
        title={c.display_name}
        description={c.headline ?? undefined}
        meta={
          <>
            {c.access === 'PROFILE' && <Badge variant="muted">Marketplace profile</Badge>}
            {c.source === 'IMPORTED' && <Badge variant="violet">Imported by your company</Badge>}
            {(c.applications ?? []).length > 0 && <Badge variant="info">Applied to your jobs</Badge>}
            <span className="text-xs text-muted-foreground">
              Profile updated {dates.relative(c.updated_at)}
            </span>
          </>
        }
        actions={
          hasResume ? (
            <Button asChild variant="outline">
              <a href="#candidate-resumes">Résumé</a>
            </Button>
          ) : undefined
        }
      />
      {c.access === 'PROFILE' && (
        <Alert variant="info" className="mb-6" title="Limited view">
          This candidate shares a marketplace profile. Contact details and résumé files are available once
          they apply to one of your jobs.
        </Alert>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <CandidateMatchPanel
            candidateId={c.id}
            jobId={jobId}
            onJobChange={(j) => update({ job_id: j }, { resetPage: false })}
            applicationJobIds={applicationJobIds}
          />
          <SummarySection c={c} />
          <SkillsSection c={c} />
          <ExperienceSection c={c} />
          <EducationSection c={c} />
          <CertificationsSection c={c} />
          <LanguagesSection c={c} />
        </div>
        <div className="min-w-0" id="candidate-resumes">
          <Sidebar c={c} />
        </div>
      </div>
    </>
  )
}
