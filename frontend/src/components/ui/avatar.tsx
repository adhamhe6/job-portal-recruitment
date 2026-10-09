import * as AvatarPrimitive from '@radix-ui/react-avatar'
import type * as React from 'react'
import { cn, initials } from '@/lib/utils'

const SIZES = {
  xs: 'size-6 text-[10px]',
  sm: 'size-8 text-xs',
  md: 'size-10 text-sm',
  lg: 'size-14 text-lg',
  xl: 'size-20 text-2xl',
}

/** Image avatar with initials fallback (company logos, user avatars). */
export function Avatar({
  name,
  src,
  size = 'md',
  shape = 'circle',
  className,
}: {
  name: string
  src?: string | null
  size?: keyof typeof SIZES
  shape?: 'circle' | 'square'
  className?: string
}) {
  return (
    <AvatarPrimitive.Root
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden border bg-primary-soft font-semibold text-primary-soft-foreground select-none',
        shape === 'circle' ? 'rounded-full' : 'rounded-xl',
        SIZES[size],
        className,
      )}
    >
      {src && <AvatarPrimitive.Image src={src} alt="" className="size-full object-cover" />}
      <AvatarPrimitive.Fallback delayMs={src ? 300 : 0} aria-hidden>
        {initials(name)}
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  )
}

export type AvatarImageProps = React.ComponentProps<typeof AvatarPrimitive.Image>
