import { ArrowRight, Briefcase, FileUp, MapPin, Search, Sparkles, Target } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { NoResults } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { useFeaturedJobs } from '@/features/jobs/api/jobs'
import { JobResults } from '@/features/jobs/components/JobResults'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { fmt } from '@/lib/format'
import { paths } from '@/routes/paths'

const QUICK_FILTERS = [
  { label: 'Remote', to: `${paths.jobs}?workplace_type=REMOTE` },
  { label: 'Hybrid', to: `${paths.jobs}?workplace_type=HYBRID` },
  { label: 'Full-time', to: `${paths.jobs}?employment_type=FULL_TIME` },
  { label: 'Senior', to: `${paths.jobs}?experience_level=SENIOR` },
  { label: 'Posted this week', to: `${paths.jobs}?posted_within_days=7` },
]

const STEPS = [
  {
    icon: FileUp,
    title: 'Upload your résumé once',
    text: 'We read it, suggest your skills and experience, and you stay in control of what is saved.',
  },
  {
    icon: Target,
    title: 'See why a job fits',
    text: 'Every match shows the skills you have, the ones related to yours and what is missing: no black box.',
  },
  {
    icon: Sparkles,
    title: 'Apply and track',
    text: 'Follow each application from screening to offer, with interview invites in one place.',
  },
]

export default function HomePage() {
  useDocumentTitle('Hiring, matched')
  const navigate = useNavigate()
  const { status } = useAuth()
  const featured = useFeaturedJobs(6)
  const [q, setQ] = useState('')
  const [where, setWhere] = useState('')

  const search = (e: FormEvent) => {
    e.preventDefault()
    const params = new URLSearchParams()
    if (q.trim()) params.set('q', q.trim())
    if (where.trim()) params.set('location', where.trim())
    const qs = params.toString()
    navigate(qs ? `${paths.jobs}?${qs}` : paths.jobs)
  }

  const total = featured.data?.total

  return (
    <>
      <section className="relative isolate overflow-hidden border-b bg-gradient-to-b from-primary-soft/70 via-background to-background">
        <div
          aria-hidden
          className="absolute -top-32 left-1/2 -z-10 size-[42rem] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl"
        />
        <div className="mx-auto max-w-7xl px-4 pt-14 pb-16 sm:px-6 sm:pt-20 sm:pb-24 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <p className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border bg-card/80 px-3.5 py-1 text-sm font-medium text-primary-soft-foreground shadow-xs backdrop-blur">
              <Sparkles className="size-4 text-primary" aria-hidden />
              Explainable candidate–job matching
            </p>
            <h1 className="text-4xl leading-[1.1] font-semibold tracking-tight text-balance sm:text-5xl lg:text-6xl">
              Find work that fits,{' '}
              <span className="bg-gradient-to-r from-indigo-600 to-violet-600 bg-clip-text text-transparent dark:from-indigo-400 dark:to-violet-400">
                and see why.
              </span>
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-lg text-pretty text-muted-foreground">
              TalentLens reads résumés and job descriptions the same way, so candidates find the roles they
              are genuinely suited for and employers meet the people who match.
            </p>
          </div>

          <form
            role="search"
            aria-label="Search jobs"
            onSubmit={search}
            className="mx-auto mt-9 grid max-w-3xl gap-2 rounded-2xl border bg-card p-2 shadow-lg sm:grid-cols-[1fr_1fr_auto]"
          >
            <div className="relative">
              <Search
                className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                aria-label="Job title, skill or keyword"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Job title, skill or keyword"
                className="h-12 border-0 pl-10 text-base shadow-none focus-visible:outline-offset-0"
              />
            </div>
            <div className="relative">
              <MapPin
                className="pointer-events-none absolute top-1/2 left-3.5 size-4.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                aria-label="Location"
                value={where}
                onChange={(e) => setWhere(e.target.value)}
                placeholder="City or country"
                className="h-12 border-0 pl-10 text-base shadow-none focus-visible:outline-offset-0 sm:border-l sm:rounded-none"
              />
            </div>
            <Button type="submit" size="lg" className="h-12 px-7">
              Search jobs
            </Button>
          </form>

          <ul
            className="mx-auto mt-5 flex max-w-3xl flex-wrap justify-center gap-2"
            aria-label="Popular searches"
          >
            {QUICK_FILTERS.map((f) => (
              <li key={f.label}>
                <Link
                  to={f.to}
                  className="inline-flex h-8 items-center rounded-full border bg-card/80 px-3.5 text-sm font-medium transition-colors hover:border-primary/40 hover:bg-accent"
                >
                  {f.label}
                </Link>
              </li>
            ))}
          </ul>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            {status === 'authenticated' ? (
              <Button asChild size="lg" variant="outline">
                <Link to={paths.dashboard}>
                  Go to your dashboard <ArrowRight />
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild size="lg" variant="outline">
                  <Link to={paths.register}>Create a candidate account</Link>
                </Button>
                <Button asChild size="lg" variant="ghost">
                  <Link to={paths.registerEmployer}>
                    <Briefcase /> I’m hiring
                  </Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </section>

      <section aria-labelledby="featured-heading" className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="featured-heading" className="text-2xl font-semibold tracking-tight">
              Latest openings
            </h2>
            <p className="mt-1 text-muted-foreground">
              {total !== undefined
                ? `${fmt.int(total)} open ${total === 1 ? 'role' : 'roles'} right now.`
                : 'Freshly published roles from employers on TalentLens.'}
            </p>
          </div>
          <Button asChild variant="outline">
            <Link to={paths.jobs}>
              Browse all jobs <ArrowRight />
            </Link>
          </Button>
        </div>
        <JobResults
          query={featured}
          skeletons={3}
          onPageChange={() => {}}
          empty={
            <NoResults
              title="No open roles right now"
              description="Check back soon, or create an account to get notified about new roles."
              action={
                <Button asChild>
                  <Link to={paths.register}>Create an account</Link>
                </Button>
              }
            />
          }
        />
      </section>

      <section aria-labelledby="how-heading" className="border-y bg-surface">
        <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
          <h2 id="how-heading" className="text-center text-2xl font-semibold tracking-tight">
            How TalentLens works
          </h2>
          <ol className="mt-8 grid gap-5 md:grid-cols-3">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <li key={title}>
                <Card className="h-full">
                  <CardContent className="space-y-3 p-6">
                    <div className="flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary-soft-foreground">
                      <Icon className="size-5" aria-hidden />
                    </div>
                    <h3 className="font-semibold">
                      <span className="mr-2 text-muted-foreground tabular">{i + 1}.</span>
                      {title}
                    </h3>
                    <p className="text-sm text-muted-foreground">{text}</p>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="cta-heading" className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-5 md:grid-cols-2">
          <Card className="bg-gradient-to-br from-primary-soft/60 to-card">
            <CardContent className="space-y-3 p-7">
              <h2 id="cta-heading" className="text-xl font-semibold tracking-tight">
                For candidates
              </h2>
              <p className="text-muted-foreground">
                Create a profile, get ranked recommendations and keep every application in one place.
              </p>
              <Button asChild>
                <Link to={paths.register}>Get started free</Link>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-3 p-7">
              <h2 className="text-xl font-semibold tracking-tight">For employers</h2>
              <p className="text-muted-foreground">
                Post a job, see ranked and explained candidate matches, and run your whole pipeline.
              </p>
              <Button asChild variant="outline">
                <Link to={paths.registerEmployer}>Register your company</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </section>
    </>
  )
}
