import { useId } from 'react'
import { DebouncedInput } from '@/components/common/DebouncedInput'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Label } from '@/components/ui/label'
import { CheckboxGroup } from '@/features/candidates/components/CheckboxGroup'
import { AVAILABILITY_OPTIONS } from '@/features/candidates/lib/filters'
import { countActiveFilters, type MatchingFilterState } from '../lib/matching'

/** Filters for the ranked list. A pure function of the URL state: every change calls `update(patch)`. */
export function MatchingFilters({
  state,
  update,
  onClear,
}: {
  state: MatchingFilterState
  update: (patch: Partial<MatchingFilterState>) => void
  onClear: () => void
}) {
  const uid = useId()
  const active = countActiveFilters(state)
  return (
    <form
      aria-label="Ranking filters"
      className="grid gap-5 rounded-xl border bg-card p-4 sm:p-5"
      onSubmit={(e) => e.preventDefault()}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          Filters{active > 0 && <span className="ml-1.5 text-muted-foreground tabular">({active})</span>}
        </h2>
        {active > 0 && (
          <Button type="button" variant="link" size="sm" onClick={onClear}>
            Clear all
          </Button>
        )}
      </div>
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Minimum score (%)" hint="0–100">
          <DebouncedInput
            type="number"
            min={0}
            max={100}
            step={5}
            inputMode="numeric"
            placeholder="e.g. 60"
            value={state.min_score}
            onValueChange={(v) => update({ min_score: v })}
          />
        </Field>
        <Field label="Minimum experience (years)">
          <DebouncedInput
            type="number"
            min={0}
            max={70}
            step={1}
            inputMode="numeric"
            placeholder="e.g. 3"
            value={state.min_experience}
            onValueChange={(v) => update({ min_experience: v })}
          />
        </Field>
        <Field label="Location">
          <DebouncedInput
            value={state.location}
            onValueChange={(v) => update({ location: v })}
            placeholder="City or country"
            autoComplete="off"
          />
        </Field>
        <div className="flex items-end pb-1.5">
          <div className="flex items-center gap-2.5">
            <Checkbox
              id={`${uid}-applicants`}
              checked={state.applicants_only === 'true'}
              onCheckedChange={(c) => update({ applicants_only: c === true ? 'true' : '' })}
            />
            <Label htmlFor={`${uid}-applicants`} className="cursor-pointer font-normal">
              Only people who applied to this job
            </Label>
          </div>
        </div>
      </div>
      <CheckboxGroup
        inline
        legend="Availability"
        options={AVAILABILITY_OPTIONS}
        values={state.availability}
        onChange={(v) => update({ availability: v })}
      />
    </form>
  )
}
