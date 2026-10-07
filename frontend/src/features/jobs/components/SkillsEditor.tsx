import { Trash2 } from 'lucide-react'
import {
  Controller,
  useFieldArray,
  useWatch,
  type Control,
  type FieldErrors,
  type UseFormRegister,
} from 'react-hook-form'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SkillPicker } from '@/features/skills/components/SkillPicker'
import { cn } from '@/lib/utils'
import type { JobFormValues } from '../lib/jobForm'

function RequirementToggle({
  value,
  onChange,
  name,
}: {
  value: 'REQUIRED' | 'PREFERRED'
  onChange: (v: 'REQUIRED' | 'PREFERRED') => void
  name: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={`Requirement level for ${name}`}
      className="inline-grid grid-cols-2 gap-0.5 rounded-lg bg-muted p-0.5 text-xs"
    >
      {(
        [
          ['REQUIRED', 'Required'],
          ['PREFERRED', 'Preferred'],
        ] as const
      ).map(([v, label]) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          className={cn(
            'h-7 cursor-pointer rounded-md px-2.5 font-medium text-muted-foreground transition-colors',
            value === v && 'bg-card text-foreground shadow-sm',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/**
 * Skills of a job: add through the async SkillPicker (existing skills, or a new one by typing a name), then set each
 * as REQUIRED / PREFERRED with an optional minimum number of years.
 */
export function SkillsEditor({
  control,
  register,
  errors,
  inputId,
  describedBy,
}: {
  control: Control<JobFormValues>
  register: UseFormRegister<JobFormValues>
  errors: FieldErrors<JobFormValues>
  inputId: string
  describedBy?: string
}) {
  const { fields, append, remove } = useFieldArray({ control, name: 'skills' })
  const watched = useWatch({ control, name: 'skills' })
  const required = (watched ?? []).filter((s) => s.requirement === 'REQUIRED').length
  const preferred = fields.length - required
  const rootError =
    errors.skills?.root?.message ??
    (typeof errors.skills?.message === 'string' ? errors.skills.message : undefined)

  return (
    <div className="grid gap-3">
      <SkillPicker
        id={inputId}
        allowCreate
        placeholder="Search or add a skill…"
        aria-describedby={describedBy}
        aria-invalid={Boolean(rootError) || undefined}
        selected={fields.map((f) => ({ id: f.skill_id, name: f.name }))}
        onAdd={(s) => append({ skill_id: s.id, name: s.name, requirement: 'REQUIRED', min_years: '' })}
        onRemove={(s) => {
          const idx = fields.findIndex((f) =>
            s.id && f.skill_id ? f.skill_id === s.id : f.name.toLowerCase() === s.name.toLowerCase(),
          )
          if (idx >= 0) remove(idx)
        }}
      />
      {fields.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
          No skills yet. Candidates are matched on these, so add the skills the role really needs.
        </p>
      ) : (
        <>
          <ul className="grid gap-2" aria-label="Job skills">
            {fields.map((f, i) => (
              <li
                key={f.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border bg-card p-2.5 pl-3.5"
              >
                <span className="flex min-w-0 flex-1 basis-40 items-center gap-2">
                  <span className="truncate text-sm font-medium">{f.name}</span>
                  {!f.skill_id && <Badge variant="warning">New skill</Badge>}
                </span>
                <Controller
                  control={control}
                  name={`skills.${i}.requirement`}
                  render={({ field }) => (
                    <RequirementToggle name={f.name} value={field.value} onChange={field.onChange} />
                  )}
                />
                <div className="flex items-center gap-1.5">
                  <Input
                    type="number"
                    min={0}
                    max={30}
                    step={0.5}
                    inputMode="decimal"
                    className="h-8 w-20"
                    aria-label={`Minimum years of ${f.name}`}
                    placeholder="Years"
                    aria-invalid={errors.skills?.[i]?.min_years ? true : undefined}
                    {...register(`skills.${i}.min_years`)}
                  />
                  <span className="text-xs text-muted-foreground">yrs min.</span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${f.name}`}
                  onClick={() => remove(i)}
                >
                  <Trash2 />
                </Button>
                {(errors.skills?.[i]?.min_years?.message || errors.skills?.[i]?.name?.message) && (
                  <p role="alert" className="basis-full text-xs font-medium text-destructive">
                    {errors.skills?.[i]?.min_years?.message ?? errors.skills?.[i]?.name?.message}
                  </p>
                )}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {required} required · {preferred} preferred
          </p>
        </>
      )}
    </div>
  )
}
