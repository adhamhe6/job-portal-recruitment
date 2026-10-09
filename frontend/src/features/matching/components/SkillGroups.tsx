import { ArrowRightLeft, Check, CircleDashed, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { SkillChip } from '@/components/common/SkillChip'

export interface RelatedSkill {
  required: string
  candidateHas: string
}

/** Normalises the API's `related_skills` (`{required, candidate_has}`) into a typed shape. */
export function toRelated(list: readonly Record<string, string>[]): RelatedSkill[] {
  return list.map((r) => ({ required: r.required ?? '?', candidateHas: r.candidate_has ?? '?' }))
}

function Group({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase [&_svg]:size-3.5">
        {icon}
        {title}
      </h4>
      {children}
    </div>
  )
}

/** Strong (matched) / related / missing-required / missing-preferred skill chips, hiding empty groups. */
export function SkillGroups({
  strong,
  related,
  missingRequired,
  missingPreferred,
  strongTitle = 'Matching skills',
}: {
  strong: string[]
  related: RelatedSkill[]
  missingRequired: string[]
  missingPreferred: string[]
  strongTitle?: string
}) {
  const none =
    strong.length === 0 &&
    related.length === 0 &&
    missingRequired.length === 0 &&
    missingPreferred.length === 0
  if (none) return <p className="text-sm text-muted-foreground">This job lists no skills to compare.</p>
  return (
    <div className="space-y-3">
      {strong.length > 0 && (
        <Group title={strongTitle} icon={<Check aria-hidden />}>
          <ul className="flex flex-wrap gap-1.5" aria-label={strongTitle}>
            {strong.map((s) => (
              <li key={s}>
                <SkillChip name={s} tone="matched" prefix={<Check className="size-3" aria-label="Has" />} />
              </li>
            ))}
          </ul>
        </Group>
      )}
      {related.length > 0 && (
        <Group title="Related skills" icon={<ArrowRightLeft aria-hidden />}>
          <ul className="flex flex-wrap gap-1.5" aria-label="Related skills">
            {related.map((r) => (
              <li key={`${r.required}-${r.candidateHas}`}>
                <SkillChip name={`${r.candidateHas} ≈ ${r.required}`} tone="related" />
              </li>
            ))}
          </ul>
        </Group>
      )}
      {missingRequired.length > 0 && (
        <Group title="Missing required skills" icon={<X aria-hidden />}>
          <ul className="flex flex-wrap gap-1.5" aria-label="Missing required skills">
            {missingRequired.map((s) => (
              <li key={s}>
                <SkillChip name={s} tone="missing" />
              </li>
            ))}
          </ul>
        </Group>
      )}
      {missingPreferred.length > 0 && (
        <Group title="Missing nice-to-have skills" icon={<CircleDashed aria-hidden />}>
          <ul className="flex flex-wrap gap-1.5" aria-label="Missing nice-to-have skills">
            {missingPreferred.map((s) => (
              <li key={s}>
                <SkillChip name={s} tone="preferred" />
              </li>
            ))}
          </ul>
        </Group>
      )}
    </div>
  )
}
