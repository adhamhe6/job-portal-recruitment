import { Check, ChevronsUpDown, X } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Badge } from './badge'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from './command'
import { controlClass } from './input'
import { Popover, PopoverContent, PopoverTrigger } from './popover'

export interface ComboboxOption {
  value: string
  label: string
  description?: string
  disabled?: boolean
}

interface CommonProps {
  options: readonly ComboboxOption[]
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  /** Async mode: called as the user types; client-side filtering is turned off (the parent filters/fetches). */
  onSearchChange?: (query: string) => void
  loading?: boolean
  disabled?: boolean
  id?: string
  className?: string
  'aria-label'?: string
  'aria-invalid'?: boolean | 'true' | 'false'
  'aria-describedby'?: string
}

function ComboboxShell({
  trigger,
  options,
  isSelected,
  onPick,
  searchPlaceholder = 'Search…',
  emptyText = 'No results found.',
  onSearchChange,
  loading,
  disabled,
  id,
  className,
  closeOnPick,
  ...aria
}: Omit<CommonProps, 'placeholder'> & {
  trigger: ReactNode
  isSelected: (v: string) => boolean
  onPick: (v: string) => void
  closeOnPick: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const listId = useId()
  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) {
          setQuery('')
          onSearchChange?.('')
        }
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
            'cursor-pointer items-center justify-between gap-2 text-left',
            className,
          )}
          {...aria}
        >
          {trigger}
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[var(--radix-popover-trigger-width)] min-w-64 overflow-hidden"
      >
        <Command shouldFilter={!onSearchChange} loop>
          <CommandInput
            value={query}
            onValueChange={(q) => {
              setQuery(q)
              onSearchChange?.(q)
            }}
            placeholder={searchPlaceholder}
            loading={loading}
          />
          <CommandList id={listId}>
            <CommandEmpty>{loading ? 'Searching…' : emptyText}</CommandEmpty>
            <CommandGroup>
              {options.map((o) => (
                <CommandItem
                  key={o.value}
                  value={o.value}
                  keywords={[o.label]}
                  disabled={o.disabled}
                  onSelect={() => {
                    onPick(o.value)
                    if (closeOnPick) setOpen(false)
                  }}
                >
                  <Check
                    className={cn('text-primary', isSelected(o.value) ? 'opacity-100' : 'opacity-0')}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{o.label}</span>
                    {o.description && (
                      <span className="block truncate text-xs text-muted-foreground">{o.description}</span>
                    )}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

/** Single-select searchable dropdown. */
export function Combobox({
  value,
  onChange,
  placeholder = 'Select…',
  clearable,
  ...rest
}: CommonProps & {
  value: string | null | undefined
  onChange: (value: string) => void
  clearable?: boolean
}) {
  const selected = rest.options.find((o) => o.value === value)
  return (
    <ComboboxShell
      {...rest}
      isSelected={(v) => v === value}
      onPick={(v) => onChange(clearable && v === value ? '' : v)}
      closeOnPick
      trigger={
        <span className={cn('truncate', !selected && 'text-muted-foreground')}>
          {selected?.label ?? placeholder}
        </span>
      }
    />
  )
}

/** Multi-select searchable dropdown with removable chips below the trigger. */
export function MultiSelect({
  values,
  onChange,
  placeholder = 'Select…',
  showChips = true,
  ...rest
}: CommonProps & { values: readonly string[]; onChange: (values: string[]) => void; showChips?: boolean }) {
  const labelOf = (v: string) => rest.options.find((o) => o.value === v)?.label ?? v
  const toggle = (v: string) => onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v])
  return (
    <div className="grid gap-2">
      <ComboboxShell
        {...rest}
        isSelected={(v) => values.includes(v)}
        onPick={toggle}
        closeOnPick={false}
        trigger={
          <span className={cn('truncate', values.length === 0 && 'text-muted-foreground')}>
            {values.length === 0 ? placeholder : `${values.length} selected`}
          </span>
        }
      />
      {showChips && values.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Selected">
          {values.map((v) => (
            <li key={v}>
              <Badge variant="default" className="gap-1 pr-1">
                {labelOf(v)}
                <button
                  type="button"
                  onClick={() => toggle(v)}
                  aria-label={`Remove ${labelOf(v)}`}
                  className="inline-flex size-4 cursor-pointer items-center justify-center rounded-full hover:bg-primary/15"
                >
                  <X className="size-3" aria-hidden />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
