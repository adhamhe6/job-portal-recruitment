import { useId } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { Option } from '@/lib/enums'

/** A labelled group of checkboxes bound to a string[] (multi-value filters kept in the URL). */
export function CheckboxGroup({
  legend,
  options,
  values,
  onChange,
  inline,
}: {
  legend: string
  options: Option[]
  values: string[]
  onChange: (values: string[]) => void
  /** Lay the options out in a wrapping row instead of a column. */
  inline?: boolean
}) {
  const uid = useId()
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-sm font-medium">{legend}</legend>
      <div className={inline ? 'flex flex-wrap gap-x-5 gap-y-2' : 'grid gap-2'}>
        {options.map((o) => {
          const id = `${uid}-${o.value}`
          return (
            <div key={o.value} className="flex items-center gap-2.5">
              <Checkbox
                id={id}
                checked={values.includes(o.value)}
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
      </div>
    </fieldset>
  )
}
