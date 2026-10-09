import { useId } from 'react'
import { DebouncedInput } from '@/components/common/DebouncedInput'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { NativeSelect } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SkillTagInput } from '@/features/skills/components/SkillPicker'
import { cn } from '@/lib/utils'
import { useJobOptions } from '../hooks/useJobOptions'
import {
  AVAILABILITY_OPTIONS,
  countActiveFilters,
  EDUCATION_LEVEL_OPTIONS,
  experienceRangeError,
  REMOTE_PREFERENCE_OPTIONS,
  type CandidateSearchState,
} from '../lib/filters'
import { CheckboxGroup } from './CheckboxGroup'

/**
 * The filter form. It is a pure function of the URL state: every change calls `update(patch)`, which writes the URL
 * (and therefore refetches). Rendered in the desktop sidebar and, identically, inside the mobile filter Sheet.
 */
export function CandidateFilters({
  state,
  update,
  onClear,
  hideTitle,
}: {
  state: CandidateSearchState
  update: (patch: Partial<CandidateSearchState>) => void
  onClear: () => void
  hideTitle?: boolean
}) {
  const uid = useId()
  const active = countActiveFilters(state)
  const jobs = useJobOptions()
  const rangeError = experienceRangeError(state)
  const skills = state.skill.map((name) => ({ name }))

  return (
    <form className="grid gap-6" aria-label="Candidate filters" onSubmit={(e) => e.preventDefault()}>
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

      <div className="grid gap-2.5">
        <Label htmlFor={`${uid}-skills`}>Skills</Label>
        <SkillTagInput
          id={`${uid}-skills`}
          value={skills}
          onChange={(next) => update({ skill: next.map((s) => s.name) })}
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
                ['all', 'All of these'],
                ['any', 'Any of these'],
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

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Years of experience</legend>
        <div className="grid grid-cols-2 gap-2">
          <DebouncedInput
            type="number"
            min={0}
            max={70}
            step={1}
            inputMode="numeric"
            aria-label="Minimum years of experience"
            aria-invalid={rangeError ? true : undefined}
            placeholder="Min"
            value={state.min_experience}
            onValueChange={(v) => update({ min_experience: v })}
          />
          <DebouncedInput
            type="number"
            min={0}
            max={70}
            step={1}
            inputMode="numeric"
            aria-label="Maximum years of experience"
            aria-invalid={rangeError ? true : undefined}
            placeholder="Max"
            value={state.max_experience}
            onValueChange={(v) => update({ max_experience: v })}
          />
        </div>
        {rangeError && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {rangeError}
          </p>
        )}
      </fieldset>

      <Field label="Location">
        <DebouncedInput
          value={state.location}
          onValueChange={(v) => update({ location: v })}
          placeholder="City or country"
          autoComplete="off"
        />
      </Field>

      <Field label="Minimum education">
        <NativeSelect value={state.min_education} onChange={(e) => update({ min_education: e.target.value })}>
          <option value="">Any</option>
          {EDUCATION_LEVEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>

      <Field label="Certification">
        <DebouncedInput
          value={state.certification}
          onValueChange={(v) => update({ certification: v })}
          placeholder="e.g. AWS Certified"
          autoComplete="off"
        />
      </Field>

      <CheckboxGroup
        legend="Availability"
        options={AVAILABILITY_OPTIONS}
        values={state.availability}
        onChange={(v) => update({ availability: v })}
      />
      <CheckboxGroup
        legend="Work preference"
        options={REMOTE_PREFERENCE_OPTIONS}
        values={state.remote_preference}
        onChange={(v) => update({ remote_preference: v })}
      />

      <div className="grid gap-4 rounded-lg border bg-surface p-3">
        <Field
          label="Match against a job"
          hint="Adds a match score to each result and lets you sort by it."
          error={jobs.isError ? 'Your jobs could not be loaded.' : null}
        >
          <NativeSelect
            value={state.job_id}
            onChange={(e) =>
              update({ job_id: e.target.value, ...(e.target.value ? {} : { min_match_score: '' }) })
            }
          >
            <option value="">No job</option>
            {state.job_id && !jobs.options.some((o) => o.value === state.job_id) && (
              <option value={state.job_id}>Selected job</option>
            )}
            {jobs.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {state.job_id && (
          <Field label="Minimum match (%)" hint="0–100">
            <DebouncedInput
              type="number"
              min={0}
              max={100}
              step={5}
              inputMode="numeric"
              placeholder="e.g. 60"
              value={state.min_match_score}
              onValueChange={(v) => update({ min_match_score: v })}
            />
          </Field>
        )}
      </div>

      <div className="flex items-center gap-2.5">
        <Checkbox
          id={`${uid}-applicants`}
          checked={state.applicants_only === 'true'}
          onCheckedChange={(c) => update({ applicants_only: c === true ? 'true' : '' })}
        />
        <Label htmlFor={`${uid}-applicants`} className="cursor-pointer font-normal">
          Only people who applied to my company's jobs
        </Label>
      </div>
    </form>
  )
}
