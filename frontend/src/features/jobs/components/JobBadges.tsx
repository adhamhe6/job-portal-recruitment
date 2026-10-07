import { Briefcase, Building2, Home, Laptop } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { EMPLOYMENT_TYPE_LABELS, EXPERIENCE_LEVEL_LABELS, WORKPLACE_TYPE_LABELS } from '@/lib/enums'
import type { EmploymentType, ExperienceLevel, WorkplaceType } from '@/lib/api'

const WORKPLACE_ICONS = { REMOTE: Laptop, HYBRID: Home, ONSITE: Building2 } as const

/** Workplace + employment (+ level) badges shared by cards and the detail header. */
export function JobBadges({
  workplace,
  employment,
  level,
}: {
  workplace: WorkplaceType
  employment: EmploymentType
  level?: ExperienceLevel | null
}) {
  const Icon = WORKPLACE_ICONS[workplace]
  return (
    <ul className="flex flex-wrap items-center gap-1.5" aria-label="Job type">
      <li>
        <Badge variant="info">
          <Icon aria-hidden />
          {WORKPLACE_TYPE_LABELS[workplace]}
        </Badge>
      </li>
      <li>
        <Badge variant="secondary">
          <Briefcase aria-hidden />
          {EMPLOYMENT_TYPE_LABELS[employment]}
        </Badge>
      </li>
      {level && (
        <li>
          <Badge variant="outline">{EXPERIENCE_LEVEL_LABELS[level]}</Badge>
        </li>
      )}
    </ul>
  )
}
