import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type * as React from 'react'
import { cn } from '@/lib/utils'
import { useRestoreFocus } from './use-restore-focus'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

export function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      className={cn(
        'fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-[2px] data-[state=closed]:animate-fade-out data-[state=open]:animate-fade-in',
        className,
      )}
      {...props}
    />
  )
}

const SIZES = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }

/** Centered modal. Focus is trapped and returned to the trigger by Radix; Esc / overlay click closes. */
export function DialogContent(props: DialogContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogOverlay />
      {/* Inner component mounts only while open, so it can remember what had focus at that moment. */}
      <DialogContentInner {...props} />
    </DialogPrimitive.Portal>
  )
}

type DialogContentProps = React.ComponentProps<typeof DialogPrimitive.Content> & {
  size?: keyof typeof SIZES
  hideClose?: boolean
}

function DialogContentInner({
  className,
  children,
  size = 'md',
  hideClose,
  onCloseAutoFocus,
  ...props
}: DialogContentProps) {
  const restoreFocus = useRestoreFocus(onCloseAutoFocus)
  return (
    <DialogPrimitive.Content
      className={cn(
        'fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-2xl border bg-popover p-6 text-popover-foreground shadow-xl outline-none data-[state=closed]:animate-pop-out data-[state=open]:animate-pop-in',
        SIZES[size],
        className,
      )}
      onCloseAutoFocus={restoreFocus}
      {...props}
    >
      {children}
      {!hideClose && (
        <DialogPrimitive.Close className="absolute top-4 right-4 inline-flex size-8 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
          <X className="size-4" aria-hidden />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  )
}

export function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1.5 pr-8', className)} {...props} />
}
export function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)} {...props} />
  )
}
export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn('text-lg leading-snug font-semibold tracking-tight', className)}
      {...props}
    />
  )
}
export function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn('text-sm text-muted-foreground', className)} {...props} />
}
