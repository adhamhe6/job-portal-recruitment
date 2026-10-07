import { useEffect, useRef, useState } from 'react'
import type * as React from 'react'
import { Input } from '@/components/ui/input'

/** Text/number input that commits `onValueChange` after the user pauses (filters that drive requests). */
export function DebouncedInput({
  value,
  onValueChange,
  delay = 400,
  ...props
}: Omit<React.ComponentProps<typeof Input>, 'value' | 'onChange'> & {
  value: string
  onValueChange: (v: string) => void
  delay?: number
}) {
  const [local, setLocal] = useState(value)
  const [synced, setSynced] = useState(value)
  const cb = useRef(onValueChange)
  useEffect(() => {
    cb.current = onValueChange
  })
  if (value !== synced) {
    setSynced(value)
    setLocal(value)
  }
  useEffect(() => {
    if (local === value) return
    const t = setTimeout(() => cb.current(local), delay)
    return () => clearTimeout(t)
  }, [local, value, delay])
  return (
    <Input
      {...props}
      value={local}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={(e) => {
        props.onBlur?.(e)
        if (local !== value) cb.current(local)
      }}
    />
  )
}
