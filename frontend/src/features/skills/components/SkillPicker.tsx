import { Check, ChevronsUpDown, Plus } from 'lucide-react'
import { useId, useState } from 'react'
import { SkillChip } from '@/components/common/SkillChip'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { controlClass } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/utils'
import { useSkillSearch } from '../api/skills'

export interface PickedSkill {
  /** Present for skills that exist in the taxonomy; absent for "create by name". */
  id?: string
  name: string
}

const same = (a: PickedSkill, b: PickedSkill) =>
  a.id && b.id ? a.id === b.id : a.name.trim().toLowerCase() === b.name.trim().toLowerCase()

interface SkillPickerProps {
  selected: readonly PickedSkill[]
  onAdd: (skill: PickedSkill) => void
  /** When provided, picking an already-selected skill removes it (toggle). */
  onRemove?: (skill: PickedSkill) => void
  /** Offer "Add “xyz” as a new skill" when nothing matches the typed text. */
  allowCreate?: boolean
  placeholder?: string
  disabled?: boolean
  id?: string
  className?: string
  'aria-label'?: string
  'aria-invalid'?: boolean | 'true' | 'false'
  'aria-describedby'?: string
}

/**
 * Async skill autocomplete (GET /skills?q=). A combobox: type to search, Arrow keys + Enter to pick, Esc to close.
 * The popover stays open after a pick so several skills can be added quickly.
 */
export function SkillPicker({
  selected,
  onAdd,
  onRemove,
  allowCreate,
  placeholder = 'Search skills (e.g. Python)…',
  disabled,
  id,
  className,
  ...aria
}: SkillPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const debounced = useDebouncedValue(query, 200)
  const search = useSkillSearch(debounced, open)
  const listId = useId()

  const results = search.data?.items ?? []
  const typed = query.trim()
  const exact = results.some((s) => s.name.toLowerCase() === typed.toLowerCase())
  const alreadyTyped = selected.some((s) => s.name.toLowerCase() === typed.toLowerCase())
  const canCreate = Boolean(allowCreate) && typed.length >= 2 && !exact && !alreadyTyped
  const loading = search.isFetching || query !== debounced

  const pick = (skill: PickedSkill) => {
    const isSelected = selected.some((s) => same(s, skill))
    if (isSelected) onRemove?.(skill)
    else onAdd(skill)
    setQuery('')
  }

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) setQuery('')
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-haspopup="listbox"
          disabled={disabled}
          className={cn(
            controlClass,
            'cursor-pointer items-center justify-between gap-2 text-left text-muted-foreground',
            className,
          )}
          {...aria}
        >
          <span className="truncate">{placeholder}</span>
          <ChevronsUpDown className="size-4 shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[var(--radix-popover-trigger-width)] min-w-72 overflow-hidden"
      >
        <Command shouldFilter={false} loop label="Skills">
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder="Type a skill name…"
            loading={loading}
          />
          <CommandList id={listId}>
            {!loading && results.length === 0 && !canCreate && (
              <CommandEmpty>No skills found{typed ? ` for “${typed}”` : ''}.</CommandEmpty>
            )}
            {results.length > 0 && (
              <CommandGroup heading={typed ? 'Matching skills' : 'Popular skills'}>
                {results.map((s) => {
                  const isSelected = selected.some((x) => same(x, { id: s.id, name: s.name }))
                  return (
                    <CommandItem key={s.id} value={s.id} onSelect={() => pick({ id: s.id, name: s.name })}>
                      <Check
                        className={cn('text-primary', isSelected ? 'opacity-100' : 'opacity-0')}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1 truncate">{s.name}</span>
                      {s.category && (
                        <span className="shrink-0 text-xs text-muted-foreground">{s.category}</span>
                      )}
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            )}
            {canCreate && (
              <CommandGroup heading="Not in the list?">
                <CommandItem value={`__create__${typed}`} onSelect={() => pick({ name: typed })}>
                  <Plus aria-hidden />
                  <span className="truncate">Add “{typed}” as a new skill</span>
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

/** SkillPicker + removable chips for the current selection (used by filters and simple forms). */
export function SkillTagInput({
  value,
  onChange,
  allowCreate,
  placeholder,
  chipsLabel = 'Selected skills',
  ...rest
}: {
  value: PickedSkill[]
  onChange: (value: PickedSkill[]) => void
  allowCreate?: boolean
  placeholder?: string
  chipsLabel?: string
  id?: string
  'aria-label'?: string
}) {
  return (
    <div className="grid gap-2">
      <SkillPicker
        selected={value}
        allowCreate={allowCreate}
        placeholder={placeholder}
        onAdd={(s) => onChange([...value, s])}
        onRemove={(s) => onChange(value.filter((x) => !same(x, s)))}
        {...rest}
      />
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={chipsLabel}>
          {value.map((s) => (
            <li key={s.id ?? s.name}>
              <SkillChip
                name={s.name}
                tone="required"
                onRemove={() => onChange(value.filter((x) => !same(x, s)))}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
