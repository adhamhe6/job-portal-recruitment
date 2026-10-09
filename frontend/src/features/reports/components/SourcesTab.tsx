import { ChartCard } from '@/components/common/ChartCard'
import { EmptyState } from '@/components/common/States'
import { fmt } from '@/lib/format'
import { useSourceStatistics, useTopSkills } from '../api/reports'
import type { ReportFilters } from '../api/types'
import { HBarChart, SimpleTable } from './charts'
import { QueryCard } from './QueryCard'

const SCOPE_NOTE = {
  company: 'Based on your company’s published jobs and their applicants.',
  assigned_jobs: 'Based on the jobs assigned to you and their applicants.',
  platform: 'Based on every published job and applicant on the platform.',
} as const

export function SourcesTab({ filters }: { filters: ReportFilters }) {
  const sources = useSourceStatistics(filters)
  const skills = useTopSkills()
  const rows = sources.data?.items ?? []
  const requested = skills.data?.requested ?? []
  const available = skills.data?.available ?? []

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <ChartCard
          title="Applications by source"
          description="Where applications come from in the selected period"
          loading={sources.isPending}
          error={sources.isError ? sources.error : undefined}
          onRetry={() => sources.refetch()}
          height={240}
          srSummary={rows.map((r) => `${fmt.label(r.source)}: ${r.applications} applications`).join('; ')}
        >
          {rows.length === 0 ? (
            <EmptyState compact title="No applications in this period" />
          ) : (
            <HBarChart
              data={rows.map((r) => ({
                label: fmt.label(r.source),
                value: r.applications,
                text: `${fmt.int(r.applications)} · ${fmt.percent(r.share, 0)}`,
              }))}
              name="Applications"
              rightMargin={84}
              labelWidth={110}
            />
          )}
        </ChartCard>
        <QueryCard
          title="Source quality"
          description="Shortlist and hire rate per source"
          loading={sources.isPending}
          error={sources.isError ? sources.error : undefined}
          onRetry={() => sources.refetch()}
          empty={rows.length === 0 ? <EmptyState compact title="No sources to compare" /> : undefined}
        >
          <SimpleTable
            caption="Application sources"
            rows={rows}
            rowKey={(r) => r.source}
            className="border-0 shadow-none"
            columns={[
              { key: 'source', header: 'Source', cell: (r) => fmt.label(r.source) },
              { key: 'apps', header: 'Applications', align: 'right', cell: (r) => fmt.int(r.applications) },
              { key: 'short', header: 'Shortlisted', align: 'right', cell: (r) => `${fmt.int(r.reached_shortlist)} (${fmt.percent(r.shortlist_rate, 0)})` },
              { key: 'hires', header: 'Hired', align: 'right', cell: (r) => `${fmt.int(r.hires)} (${fmt.percent(r.hire_rate, 0)})` },
            ]}
          />
        </QueryCard>
      </div>

      <p className="text-sm text-muted-foreground">
        {skills.data ? SCOPE_NOTE[skills.data.scope] : 'Skills demand compares what jobs ask for with what applicants have.'}{' '}
        The skills reports are a current snapshot; the date range does not apply.
      </p>
      <div className="grid gap-5 lg:grid-cols-2">
        <ChartCard
          title="Most requested skills"
          description={skills.data ? `Skills listed by ${skills.data.jobs_considered} published jobs` : 'Skills listed by published jobs'}
          loading={skills.isPending}
          error={skills.isError ? skills.error : undefined}
          onRetry={() => skills.refetch()}
          height={320}
          srSummary={requested.map((s) => `${s.skill}: ${s.jobs} jobs`).join('; ')}
        >
          {requested.length === 0 ? (
            <EmptyState compact title="No published jobs list skills yet" />
          ) : (
            <HBarChart
              data={requested.map((s) => ({ label: s.skill, value: s.jobs, text: `${s.jobs} (${s.required_in_jobs} req.)` }))}
              name="Jobs requesting the skill"
              rightMargin={84}
            />
          )}
        </ChartCard>
        <ChartCard
          title="Most common applicant skills"
          description={skills.data ? `Confirmed skills of ${skills.data.applicants_considered} applicants` : 'Confirmed skills of applicants'}
          loading={skills.isPending}
          error={skills.isError ? skills.error : undefined}
          onRetry={() => skills.refetch()}
          height={320}
          srSummary={available.map((s) => `${s.skill}: ${s.candidates} candidates`).join('; ')}
        >
          {available.length === 0 ? (
            <EmptyState compact title="No applicant skills yet" />
          ) : (
            <HBarChart
              data={available.map((s) => ({ label: s.skill, value: s.candidates }))}
              name="Applicants with the skill"
              color="var(--chart-3)"
            />
          )}
        </ChartCard>
      </div>
    </div>
  )
}
