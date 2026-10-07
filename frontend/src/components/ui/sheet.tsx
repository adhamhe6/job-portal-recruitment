import * as SheetPrimitive from '@radix-ui/react-dialog'
import { cva, type VariantProps } from 'class-variance-authority'
import { X } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { useRestoreFocus } from './use-restore-focus'

/** Slide-over panel (mobile navigation, filter drawers, detail panels). Built on Radix Dialog: focus trap, Esc, return focus. */
export const Sheet = SheetPrimitive.Root
export const SheetTrigger = SheetPrimitive.Trigger
export const SheetClose = SheetPrimitive.Close

const sheetVariants = cva(
  'fixed z-50 flex flex-col gap-4 bg-popover text-popover-foreground shadow-xl outline-none data-[state=closed]:duration-150',
  {
    variants: {
      side: {
        right:
          'inset-y-0 right-0 h-full w-[min(26rem,100vw)] border-l data-[state=closed]:animate-slide-out-right data-[state=open]:animate-slide-in-right',
        left: 'inset-y-0 left-0 h-full w-[min(20rem,88vw)] border-r data-[state=closed]:animate-slide-out-left data-[state=open]:animate-slide-in-left',
        bottom:
          'inset-x-0 bottom-0 max-h-[88dvh] rounded-t-2xl border-t data-[state=closed]:animate-slide-out-bottom data-[state=open]:animate-slide-in-bottom',
      },
    },
    defaultVariants: { side: 'right' },
  },
)

type SheetContentProps = React.ComponentProps<typeof SheetPrimitive.Content> &
  VariantProps<typeof sheetVariants> & { hideClose?: boolean }

export function SheetContent(props: SheetContentProps) {
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-[2px] data-[state=closed]:animate-fade-out data-[state=open]:animate-fade-in" />
      {/* Inner component mounts only while open, so it can remember what had focus at that moment. */}
      <SheetContentInner {...props} />
    </SheetPrimitive.Portal>
  )
}

function SheetContentInner({
  side,
  className,
  children,
  hideClose,
  onCloseAutoFocus,
  ...props
}: SheetContentProps) {
  const restoreFocus = useRestoreFocus(onCloseAutoFocus)
  return (
    <SheetPrimitive.Content
      className={cn(sheetVariants({ side }), className)}
      onCloseAutoFocus={restoreFocus}
      {...props}
    >
      {children}
      {!hideClose && (
        <SheetPrimitive.Close className="absolute top-3.5 right-3.5 inline-flex size-8 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
          <X className="size-4" aria-hidden />
          <span className="sr-only">Close</span>
        </SheetPrimitive.Close>
      )}
    </SheetPrimitive.Content>
  )
}
export function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 border-b px-5 py-4 pr-12', className)} {...props} />
}
export function SheetBody({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5', className)} {...props} />
}
export function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex gap-2 border-t px-5 py-3', className)} {...props} />
}
export function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title className={cn('text-base font-semibold tracking-tight', className)} {...props} />
  )
}
export function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return <SheetPrimitive.Description className={cn('text-sm text-muted-foreground', className)} {...props} />
}
