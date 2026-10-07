import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import type { ReactNode } from 'react'
import { Pagination } from '@/components/ui/pagination'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/utils'
import { EmptyState, ErrorState, TableSkeleton } from './States'

export interface Column<T> {
  key: string
  header: ReactNode
  cell: (row: T) => ReactNode
  /** Enables a sortable header button; the value is passed to `onSortChange`. */
  sortKey?: string
  align?: 'left' | 'right' | 'center'
  className?: string
  headerClassName?: string
  /** Hide the column below this breakpoint (the table still scrolls horizontally if needed). */
  hideBelow?: 'sm' | 'md' | 'lg' | 'xl'
}

const HIDE = { sm: 'hidden sm:table-cell', md: 'hidden md:table-cell', lg: 'hidden lg:table-cell', xl: 'hidden xl:table-cell' }
const ALIGN = { left: 'text-left', right: 'text-right', center: 'text-center' }

export interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[] | undefined
  rowKey: (row: T) => string
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  /** Currently sorted column's `sortKey` and direction. */
  sortKey?: string
  sortDirection?: 'asc' | 'desc'
  onSortChange?: (sortKey: string) => void
  /** Row is clickable/keyboard-activatable when provided. Interactive children keep their own behaviour. */
  onRowClick?: (row: T) => void
  /** Rendered when `rows` is empty. */
  empty?: ReactNode
  /** On screens below md, render each row with this instead of a table (cards). */
  renderCard?: (row: T) => ReactNode
  caption: string
  // pagination (server-side)
  page?: number
  pages?: number
  pageSize?: number
  total?: number
  onPageChange?: (page: number) => void
  className?: string
}

/**
 * Responsive data table. Desktop: semantic <table> in a horizontal-scroll container (never stretches the page).
 * Mobile: cards via `renderCard` when supplied. Built-in loading skeleton, error (with retry) and empty states,
 * sortable headers (`aria-sort`) and server-side pagination.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  onRetry,
  sortKey,
  sortDirection,
  onSortChange,
  onRowClick,
  empty,
  renderCard,
  caption,
  page,
  pages,
  pageSize,
  total,
  onPageChange,
  className,
}: DataTableProps<T>) {
  const isDesktop = useIsDesktop()

  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (loading && !rows) return <TableSkeleton cols={Math.min(columns.length, 6)} />
  if (rows && rows.length === 0) return <>{empty ?? <EmptyState title="Nothing here yet" description="There are no records to show." />}</>

  const pager =
    page !== undefined && pages !== undefined && onPageChange ? (
      <Pagination page={page} pages={pages} total={total} pageSize={pageSize} onPageChange={onPageChange} className="border-t px-4" />
    ) : null

  if (!isDesktop && renderCard) {
    return (
      <div className={cn(loading && 'opacity-60 transition-opacity', className)} aria-busy={loading || undefined}>
        <ul className="divide-y" aria-label={caption}>
          {rows?.map((row) => (
            <li key={rowKey(row)}>{renderCard(row)}</li>
          ))}
        </ul>
        {pager}
      </div>
    )
  }

  return (
    <div className={cn(loading && 'opacity-60 transition-opacity', className)} aria-busy={loading || undefined}>
      <Table>
        <caption className="sr-only">{caption}</caption>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((c) => {
              const active = c.sortKey !== undefined && sortKey === c.sortKey
              return (
                <TableHead
                  key={c.key}
                  scope="col"
                  className={cn(c.hideBelow && HIDE[c.hideBelow], c.align && ALIGN[c.align], c.headerClassName)}
                  aria-sort={active ? (sortDirection === 'desc' ? 'descending' : 'ascending') : undefined}
                >
                  {c.sortKey && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => onSortChange(c.sortKey as string)}
                      className={cn(
                        'inline-flex cursor-pointer items-center gap-1 rounded-sm uppercase hover:text-foreground',
                        active && 'text-foreground',
                        c.align === 'right' && 'flex-row-reverse',
                      )}
                    >
                      {c.header}
                      {active ? (
                        sortDirection === 'desc' ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUp className="size-3" aria-hidden />
                      ) : (
                        <ArrowUpDown className="size-3 opacity-40" aria-hidden />
                      )}
                    </button>
                  ) : (
                    c.header
                  )}
                </TableHead>
              )
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows?.map((row) => (
            <TableRow
              key={rowKey(row)}
              className={cn(onRowClick && 'cursor-pointer')}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.target !== e.currentTarget) return // nested buttons/links keep their own keys
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onRowClick(row)
                      }
                    }
                  : undefined
              }
              tabIndex={onRowClick ? 0 : undefined}
            >
              {columns.map((c) => (
                <TableCell key={c.key} className={cn(c.hideBelow && HIDE[c.hideBelow], c.align && ALIGN[c.align], c.className)}>
                  {c.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {pager}
    </div>
  )
}
