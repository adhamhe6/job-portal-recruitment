import { Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/**
 * Debounced search box: keeps typing snappy and sends one request per pause instead of one per keystroke.
 * `value` is the committed (URL/query) value; external changes (e.g. "Clear filters") are adopted.
 * Enter commits immediately.
 */
export function SearchInput({
  value,
  onChange,
  placeholder = 'Search…',
  label,
  className,
  delay = 350,
  autoFocus,
  id,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  /** Accessible name (defaults to the placeholder). */
  label?: string
  className?: string
  delay?: number
  autoFocus?: boolean
  id?: string
}) {
  const [local, setLocal] = useState(value)
  const [synced, setSynced] = useState(value)
  const onChangeRef = useRef(onChange)
  useEffect(() => {
    onChangeRef.current = onChange
  })

  // Adopt external changes during render (React-recommended alternative to an effect).
  if (value !== synced) {
    setSynced(value)
    setLocal(value)
  }

  useEffect(() => {
    if (local === value) return
    const t = setTimeout(() => onChangeRef.current(local), delay)
    return () => clearTimeout(t)
  }, [local, value, delay])

  return (
    <div className={cn('relative w-full', className)}>
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <Input
        id={id}
        type="search"
        role="searchbox"
        aria-label={label ?? placeholder}
        placeholder={placeholder}
        value={local}
        autoFocus={autoFocus}
        onChange={(e) => setLocal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onChangeRef.current(local)
        }}
        className="pr-9 pl-9 [&::-webkit-search-cancel-button]:hidden"
      />
      {local && (
        <button
          type="button"
          aria-label="Clear search"
          className="absolute top-1/2 right-2 inline-flex size-6 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={() => {
            setLocal('')
            onChangeRef.current('')
          }}
        >
          <X className="size-3.5" aria-hidden />
        </button>
      )}
    </div>
  )
}
