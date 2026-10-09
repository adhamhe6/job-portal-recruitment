import { Briefcase, ExternalLink, GraduationCap, Languages as LanguagesIcon, Award } from 'lucide-react'
import type { ReactNode } from 'react'
import { SkillChip } from '@/components/common/SkillChip'
import { TextBlock } from '@/components/common/TextBlock'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EDUCATION_LEVEL_LABELS } from '@/lib/enums'
import { dates, fmt } from '@/lib/format'
import type { CandidateView } from '../api/candidates'
import { dateRange, LANGUAGE_PROFICIENCY_LABELS, SKILL_PROFICIENCY_LABELS, yearRange } from '../lib/profile'

export function Section({ title, icon, children }: { title: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base [&_svg]:size-4 [&_svg]:text-primary">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function SummarySection({ c }: { c: CandidateView }) {
  if (!c.summary?.trim()) return null
  return (
    <Section title="Summary">
      <TextBlock text={c.summary} />
    </Section>
  )
}

export function SkillsSection({ c }: { c: CandidateView }) {
  const visible = c.skills.filter((s) => s.status !== 'REJECTED')
  const confirmed = visible.filter((s) => s.status === 'CONFIRMED')
  const suggested = visible.filter((s) => s.status === 'SUGGESTED')
  return (
    <Section title="Skills">
      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">No skills listed.</p>
      ) : (
        <div className="space-y-4">
          {confirmed.length > 0 && (
            <ul className="flex flex-wrap gap-2" aria-label="Skills">
              {confirmed.map((s) => {
                const detail = [
                  s.proficiency ? SKILL_PROFICIENCY_LABELS[s.proficiency] : null,
                  s.years_experience ? `${fmt.num(s.years_experience)} yrs` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')
                return (
                  <li key={s.id}>
                    <SkillChip name={detail ? `${s.skill.name} (${detail})` : s.skill.name} tone="required" />
                  </li>
                )
              })}
            </ul>
          )}
          {suggested.length > 0 && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Found in the résumé, not yet confirmed
              </h4>
              <ul className="flex flex-wrap gap-2" aria-label="Unconfirmed skills">
                {suggested.map((s) => (
                  <li key={s.id}>
                    <SkillChip name={s.skill.name} tone="preferred" />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}

export function ExperienceSection({ c }: { c: CandidateView }) {
  if (c.experiences.length === 0) return null
  return (
    <Section title="Experience" icon={<Briefcase aria-hidden />}>
      <ol className="space-y-5">
        {c.experiences.map((e) => (
          <li key={e.id} className="space-y-1">
            <p className="font-medium">{e.title}</p>
            <p className="text-sm text-muted-foreground">
              {e.company_name}
              {e.location ? ` · ${e.location}` : ''}
              {' · '}
              {dateRange(e.start_date, e.end_date, e.is_current)}
            </p>
            <TextBlock text={e.description} className="text-sm" />
          </li>
        ))}
      </ol>
    </Section>
  )
}

export function EducationSection({ c }: { c: CandidateView }) {
  if (c.educations.length === 0) return null
  return (
    <Section title="Education" icon={<GraduationCap aria-hidden />}>
      <ul className="space-y-4">
        {c.educations.map((e) => (
          <li key={e.id}>
            <p className="font-medium">{e.degree || EDUCATION_LEVEL_LABELS[e.degree_level]}</p>
            <p className="text-sm text-muted-foreground">
              {e.institution}
              {e.field_of_study ? ` · ${e.field_of_study}` : ''}
              {yearRange(e.start_year, e.end_year) ? ` · ${yearRange(e.start_year, e.end_year)}` : ''}
            </p>
          </li>
        ))}
      </ul>
    </Section>
  )
}

export function CertificationsSection({ c }: { c: CandidateView }) {
  if (c.certifications.length === 0) return null
  return (
    <Section title="Certifications" icon={<Award aria-hidden />}>
      <ul className="space-y-3">
        {c.certifications.map((x) => (
          <li key={x.id}>
            <p className="font-medium">
              {x.credential_url ? (
                <a
                  href={x.credential_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 hover:text-primary hover:underline"
                >
                  {x.name} <ExternalLink className="size-3.5" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              ) : (
                x.name
              )}
            </p>
            <p className="text-sm text-muted-foreground">
              {[
                x.issuer,
                x.issued_on ? `Issued ${dates.date(x.issued_on)}` : null,
                x.expires_on ? `Expires ${dates.date(x.expires_on)}` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </li>
        ))}
      </ul>
    </Section>
  )
}

export function LanguagesSection({ c }: { c: CandidateView }) {
  if (c.languages.length === 0) return null
  return (
    <Section title="Languages" icon={<LanguagesIcon aria-hidden />}>
      <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {c.languages.map((l) => (
          <li key={l.id}>
            <span className="font-medium">{l.language}</span>{' '}
            <span className="text-muted-foreground">{LANGUAGE_PROFICIENCY_LABELS[l.proficiency]}</span>
          </li>
        ))}
      </ul>
    </Section>
  )
}
