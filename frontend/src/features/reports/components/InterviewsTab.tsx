import { CalendarCheck, Clock, Star, UserX } from 'lucide-react'
import { ChartCard } from '@/components/common/ChartCard'
import { KpiCard } from '@/components/common/KpiCard'
import { EmptyState } from '@/components/common/States'
import { fmt } from '@/lib/format'
import {
  INTERVIEW_STATUS_LABELS,
  INTERVIEW_TYPE_LABELS,
  RECOMMENDATION_LABELS,
} from '@/features/interviews/lib/labels'
import type { HireRecommendation, InterviewStatus, InterviewType } from '@/features/interviews/api/types'
import { useInterviewStatistics, useMatchingPerformance } from '../api/reports'
import type { ReportFilters } from '../api/types'
import { HBarChart, SimpleTable } from './charts'
import { QueryCard } from './QueryCard'

const label = <T extends string>(map: Record<T, string>, key: string) => map[key as T] ?? fmt.label(key)
const OUTCOME_LABELS: Record<string, string> = {
  HIRED: 'Hired',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
  IN_PROGRESS: 'In progress',
}
const BAND_LABELS: Record<string, string> = {
  STRONG: 'Strong',
  GOOD: 'Good',
  PARTIAL: 'Partial',
  WEAK: 'Weak',
}

export function InterviewsTab({ filters }: { filters: ReportFilters }) {
  const stats = useInterviewStatistics(filters)
  const matching = useMatchingPerformance(filters)
  const s = stats.data
  const statusData = Object.entries(s?.by_status ?? {}).map(([k, v]) => ({
    label: label<InterviewStatus>(INTERVIEW_STATUS_LABELS, k),
    value: v,
  }))
  const typeData = Object.entries(s?.by_type ?? {}).map(([k, v]) => ({
    label: label<InterviewType>(INTERVIEW_TYPE_LABELS, k).replace(/ interview$/i, ''),
    value: v,
  }))
  const recData = Object.entries(s?.feedback.recommendations ?? {}).map(([k, v]) => ({
    label: label<HireRecommendation>(RECOMMENDATION_LABELS, k),
    value: v,
  }))
  const m = matching.data

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Interviews"
          value={fmt.int(s?.total)}
          icon={<CalendarCheck />}
          hint="Starting in the selected period"
          loading={stats.isPending}
        />
        <KpiCard
          label="No-show rate"
          value={s?.no_show_rate == null ? '—' : fmt.percent(s.no_show_rate, 0)}
          icon={<UserX />}
          tone="warning"
          hint={s ? `Of ${s.held_or_missed} held or missed` : undefined}
          loading={stats.isPending}
        />
        <KpiCard
          label="Average length"
          value={s?.avg_duration_minutes == null ? '—' : `${fmt.num(s.avg_duration_minutes)} min`}
          icon={<Clock />}
          tone="info"
          hint={s?.cancellation_rate == null ? undefined : `${fmt.percent(s.cancellation_rate, 0)} cancelled`}
          loading={stats.isPending}
        />
        <KpiCard
          label="Avg. feedback rating"
          value={s?.feedback.average_rating == null ? '—' : `${fmt.num(s.feedback.average_rating)} / 5`}
          icon={<Star />}
          tone="success"
          hint={
            s
              ? `${s.feedback.entries} entries on ${s.feedback.interviews_with_feedback} interviews`
              : undefined
          }
          loading={stats.isPending}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {[
          { title: 'By status', data: statusData, name: 'Interviews' },
          { title: 'By type', data: typeData, name: 'Interviews' },
          { title: 'Feedback recommendations', data: recData, name: 'Feedback entries' },
        ].map((c) => (
          <ChartCard
            key={c.title}
            title={c.title}
            description={
              c.title === 'Feedback recommendations'
                ? 'What interviewers recommend after the interview'
                : undefined
            }
            loading={stats.isPending}
            error={stats.isError ? stats.error : undefined}
            onRetry={() => stats.refetch()}
            height={240}
            srSummary={c.data.map((d) => `${d.label}: ${d.value}`).join('; ')}
          >
            {s && c.data.every((d) => d.value === 0) ? (
              <EmptyState
                compact
                title={
                  c.title === 'Feedback recommendations' ? 'No feedback yet' : 'No interviews in this period'
                }
              />
            ) : (
              <HBarChart data={c.data} name={c.name} labelWidth={96} rightMargin={32} />
            )}
          </ChartCard>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <ChartCard
          title="Match score of applicants"
          description="How the applicants’ stored match scores spread across the bands"
          loading={matching.isPending}
          error={matching.isError ? matching.error : undefined}
          onRetry={() => matching.refetch()}
          height={240}
          srSummary={m?.applicant_distribution
            .map((b) => `${BAND_LABELS[b.band] ?? b.band}: ${b.count}`)
            .join('; ')}
        >
          {m && m.applicant_distribution.every((b) => b.count === 0) ? (
            <EmptyState compact title="No scored applicants in this period" />
          ) : (
            <HBarChart
              data={(m?.applicant_distribution ?? []).map((b) => ({
                label: BAND_LABELS[b.band] ?? b.band,
                value: b.count,
                text: `${b.count} · ${fmt.num(b.percent)}%`,
              }))}
              name="Applicants"
              rightMargin={84}
              labelWidth={72}
            />
          )}
        </ChartCard>
        <QueryCard
          title="Average match score by outcome"
          description="Descriptive only — the score is a ranking aid, not a prediction"
          loading={matching.isPending}
          error={matching.isError ? matching.error : undefined}
          onRetry={() => matching.refetch()}
        >
          <SimpleTable
            caption="Average match score by application outcome"
            rows={m?.avg_score_by_outcome ?? []}
            rowKey={(r) => r.outcome}
            className="border-0 shadow-none"
            columns={[
              { key: 'o', header: 'Outcome', cell: (r) => OUTCOME_LABELS[r.outcome] ?? fmt.label(r.outcome) },
              {
                key: 'a',
                header: 'Scored applications',
                align: 'right',
                cell: (r) => fmt.int(r.applications),
              },
              { key: 's', header: 'Avg. score', align: 'right', cell: (r) => fmt.percent(r.avg_score, 0) },
            ]}
          />
          {m && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {m.top10.pct_in_top10 !== null && (
                <li>
                  {fmt.num(m.top10.pct_in_top10)}% of scored applicants ranked in their job&apos;s top 10
                  candidates.
                </li>
              )}
              {m.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </QueryCard>
      </div>
    </div>
  )
}
