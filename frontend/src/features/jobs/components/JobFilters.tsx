import { Building2, X } from 'lucide-react'
import { useId } from 'react'
import { DebouncedInput } from '@/components/common/DebouncedInput'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { NativeSelect } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SkillTagInput } from '@/features/skills/components/SkillPicker'
import {
  EMPLOYMENT_TYPE_OPTIONS,
  EXPERIENCE_LEVEL_OPTIONS,
  POSTED_WITHIN_OPTIONS,
  WORKPLACE_TYPE_OPTIONS,
  type Option,
} from '@/lib/enums'
import { cn } from '@/lib/utils'
import { countActiveFilters, type JobSearchState } from '../lib/filters'

function CheckboxGroup({
  legend,
  options,
  values,
  onChange,
}: {
  legend: string
  options: Option[]
  values: string[]
  onChange: (values: string[]) => void
}) {
  const uid = useId()
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      {options.map((o) => {
        const id = `${uid}-${o.value}`
        const checked = values.includes(o.value)
        return (
          <div key={o.value} className="flex items-center gap-2.5">
            <Checkbox
              id={id}
              checked={checked}
              onCheckedChange={(c) =>
                onChange(c === true ? [...values, o.value] : values.filter((v) => v !== o.value))
              }
            />
            <Label htmlFor={id} className="cursor-pointer font-normal">
              {o.label}
            </Label>
          </div>
        )
      })}
    </fieldset>
  )
}

/**
 * The filter form. It is a pure function of the URL state: every change calls `update(patch)`, which writes the URL
 * (and therefore refetches). Rendered in the desktop sidebar and, identically, inside the mobile filter Sheet.
 */
export function JobFilters({
  state,
  update,
  onClear,
  companyName,
  allowSkillCreate = false,
  hideTitle = false,
}: {
  state: JobSearchState
  update: (patch: Partial<JobSearchState>) => void
  onClear: () => void
  companyName?: string | null
  allowSkillCreate?: boolean
  hideTitle?: boolean
}) {
  const uid = useId()
  const active = countActiveFilters(state)
  const skills = state.skill.map((name) => ({ name }))

  return (
    <form
      className="grid gap-6"
      aria-label="Job filters"
      onSubmit={(e) => {
        e.preventDefault()
      }}
    >
      <div className={cn('flex items-center justify-between', hideTitle && 'hidden')}>
        <h2 className="text-sm font-semibold">
          Filters{active > 0 && <span className="ml-1.5 text-muted-foreground tabular">({active})</span>}
        </h2>
        {active > 0 && (
          <Button type="button" variant="link" size="sm" onClick={onClear}>
            Clear all
          </Button>
        )}
      </div>

      {state.company_id && (
        <div className="flex items-center justify-between gap-2 rounded-lg border bg-primary-soft/50 px-3 py-2 text-sm">
          <span className="flex min-w-0 items-center gap-2">
            <Building2 className="size-4 shrink-0 text-primary" aria-hidden />
            <span className="truncate font-medium">{companyName ?? 'Selected company'}</span>
          </span>
          <button
            type="button"
            onClick={() => update({ company_id: '' })}
            aria-label="Remove company filter"
            className="inline-flex size-6 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
      )}

      <div className="grid gap-2.5">
        <Label htmlFor={`${uid}-skills`}>Skills</Label>
        <SkillTagInput
          id={`${uid}-skills`}
          value={skills}
          onChange={(next) => update({ skill: next.map((s) => s.name) })}
          allowCreate={allowSkillCreate}
          placeholder="Add a skill…"
          chipsLabel="Skill filters"
        />
        {state.skill.length > 1 && (
          <div
            role="radiogroup"
            aria-label="Skill matching"
            className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1 text-sm"
          >
            {(
              [
                ['any', 'Any of these'],
                ['all', 'All of these'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={state.skills_mode === value}
                onClick={() => update({ skills_mode: value })}
                className={cn(
                  'h-7 cursor-pointer rounded-md font-medium text-muted-foreground transition-colors',
                  state.skills_mode === value && 'bg-card text-foreground shadow-sm',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <Field label="Location">
        <DebouncedInput
          value={state.location}
          onValueChange={(v) => update({ location: v })}
          placeholder="City or country"
          autoComplete="off"
        />
      </Field>

      <CheckboxGroup
        legend="Workplace"
        options={WORKPLACE_TYPE_OPTIONS}
        values={state.workplace_type}
        onChange={(v) => update({ workplace_type: v })}
      />
      <CheckboxGroup
        legend="Employment type"
        options={EMPLOYMENT_TYPE_OPTIONS}
        values={state.employment_type}
        onChange={(v) => update({ employment_type: v })}
      />
      <CheckboxGroup
        legend="Experience level"
        options={EXPERIENCE_LEVEL_OPTIONS}
        values={state.experience_level}
        onChange={(v) => update({ experience_level: v })}
      />

      <Field label="Max. experience required" hint="Jobs asking for at most this many years">
        <DebouncedInput
          type="number"
          min={0}
          max={70}
          step={1}
          inputMode="numeric"
          placeholder="e.g. 3"
          value={state.max_experience}
          onValueChange={(v) => update({ max_experience: v })}
        />
      </Field>

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Salary range</legend>
        <div className="grid grid-cols-2 gap-2">
          <DebouncedInput
            type="number"
            min={0}
            step={1000}
            inputMode="numeric"
            aria-label="Minimum salary"
            placeholder="Min"
            value={state.salary_min}
            onValueChange={(v) => update({ salary_min: v })}
          />
          <DebouncedInput
            type="number"
            min={0}
            step={1000}
            inputMode="numeric"
            aria-label="Maximum salary"
            placeholder="Max"
            value={state.salary_max}
            onValueChange={(v) => update({ salary_max: v })}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Yearly amounts in each job's own currency; currencies aren't converted.
        </p>
      </fieldset>

      <Field label="Posted">
        <NativeSelect
          value={state.posted_within_days}
          onChange={(e) => update({ posted_within_days: e.target.value })}
        >
          <option value="">Any time</option>
          {POSTED_WITHIN_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
    </form>
  )
}
