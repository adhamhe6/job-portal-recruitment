import { Pencil, Plus, Trash2 } from 'lucide-react'
import type { FormEventHandler, ReactNode } from 'react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/** Card shell for one profile section: heading, optional "Add" action, and content. `id` is the in-page anchor. */
export function SectionCard({
  id,
  title,
  description,
  addLabel,
  onAdd,
  actions,
  children,
}: {
  id: string
  title: string
  description?: string
  addLabel?: string
  onAdd?: () => void
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <Card id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <CardTitle id={`${id}-title`} className="text-lg">
            {title}
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {onAdd && (
            <Button variant="outline" size="sm" onClick={onAdd}>
              <Plus /> {addLabel ?? 'Add'}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

/** One row of a section list with edit / delete buttons whose accessible names include the item. */
export function EntryRow({
  title,
  subtitle,
  meta,
  badge,
  onEdit,
  onDelete,
  label,
  children,
}: {
  title: ReactNode
  subtitle?: ReactNode
  meta?: ReactNode
  badge?: ReactNode
  onEdit?: () => void
  onDelete: () => void
  /** Plain-text name of the item, used in the button labels. */
  label: string
  children?: ReactNode
}) {
  return (
    <li className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2 font-medium break-words">
          {title}
          {badge}
        </p>
        {subtitle && <p className="text-sm text-foreground/80">{subtitle}</p>}
        {meta && <p className="text-xs text-muted-foreground">{meta}</p>}
        {children}
      </div>
      <div className="flex shrink-0 gap-1">
        {onEdit && (
          <Button variant="ghost" size="icon-sm" onClick={onEdit} aria-label={`Edit ${label}`}>
            <Pencil />
          </Button>
        )}
        <Button variant="ghost" size="icon-sm" onClick={onDelete} aria-label={`Delete ${label}`}>
          <Trash2 />
        </Button>
      </div>
    </li>
  )
}

/** Modal form shell: title, fields (children), form-level error and Cancel / Save buttons. */
export function EntryDialog({
  open,
  onOpenChange,
  title,
  description,
  onSubmit,
  pending,
  error,
  submitLabel = 'Save',
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  onSubmit: FormEventHandler<HTMLFormElement>
  pending?: boolean
  error?: string | null
  submitLabel?: string
  children: ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={onSubmit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description ?? 'Fields marked * are required.'}</DialogDescription>
          </DialogHeader>
          {error && <Alert variant="danger">{error}</Alert>}
          <div className="grid max-h-[60vh] gap-4 overflow-y-auto px-0.5 py-0.5">{children}</div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <Button type="submit" loading={pending}>
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
