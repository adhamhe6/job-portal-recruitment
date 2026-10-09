import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'

/** Copies `value` to the clipboard and confirms with a check mark for 2 s. */
export function CopyButton({
  value,
  label = 'Copy',
  size = 'icon-sm',
  className,
}: {
  value: string
  label?: string
  size?: 'icon' | 'icon-sm'
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <Button
      variant="ghost"
      size={size}
      className={className}
      aria-label={copied ? 'Copied' : label}
      title={copied ? 'Copied' : label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
          setCopied(true)
          clearTimeout(timer.current)
          timer.current = setTimeout(() => setCopied(false), 2000)
        } catch {
          toast.error('Could not copy to the clipboard')
        }
      }}
    >
      {copied ? <Check className="text-emerald-600" /> : <Copy />}
    </Button>
  )
}
