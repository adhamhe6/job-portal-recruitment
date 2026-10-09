import { ChevronLeft, ChevronRight } from 'lucide-react'
import { fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Button } from './button'

/** Page numbers with ellipses: [1, '…', 4, 5, 6, '…', 20]. */
export function pageWindow(page: number, pages: number, siblings = 1): (number | '…')[] {
  const total = Math.max(1, pages)
  const out: (number | '…')[] = []
  const start = Math.max(2, page - siblings)
  const end = Math.min(total - 1, page + siblings)
  out.push(1)
  if (start > 2) out.push('…')
  for (let p = start; p <= end; p++) out.push(p)
  if (end < total - 1) out.push('…')
  if (total > 1) out.push(total)
  return out
}

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  className,
  label = 'results',
}: {
  page: number
  pages: number
  total?: number
  pageSize?: number
  onPageChange: (page: number) => void
  className?: string
  /** Noun for the "Showing x–y of N …" text. */
  label?: string
}) {
  if (pages <= 1 && !total) return null
  const from = total !== undefined && pageSize ? (total === 0 ? 0 : (page - 1) * pageSize + 1) : null
  const to = total !== undefined && pageSize ? Math.min(total, page * pageSize) : null
  return (
    <nav
      aria-label="Pagination"
      className={cn('flex flex-col items-center justify-between gap-3 py-3 sm:flex-row', className)}
    >
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {from !== null && to !== null && total !== undefined ? (
          <>
            Showing{' '}
            <span className="font-medium text-foreground tabular">
              {fmt.int(from)}–{fmt.int(to)}
            </span>{' '}
            of <span className="font-medium text-foreground tabular">{fmt.int(total)}</span> {label}
          </>
        ) : (
          <>
            Page {page} of {pages}
          </>
        )}
      </p>
      {pages > 1 && (
        <ul className="flex items-center gap-1">
          <li>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
              aria-label="Previous page"
            >
              <ChevronLeft />
            </Button>
          </li>
          {pageWindow(page, pages).map((p, i) => (
            <li
              key={`${p}-${i}`}
              className={cn(
                typeof p === 'number' && p !== 1 && p !== pages && p !== page && 'hidden sm:block',
              )}
            >
              {p === '…' ? (
                <span className="px-1.5 text-muted-foreground" aria-hidden>
                  …
                </span>
              ) : (
                <Button
                  variant={p === page ? 'default' : 'outline'}
                  size="icon-sm"
                  className="tabular"
                  onClick={() => onPageChange(p)}
                  aria-label={`Page ${p}`}
                  aria-current={p === page ? 'page' : undefined}
                >
                  {p}
                </Button>
              )}
            </li>
          ))}
          <li>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= pages}
              aria-label="Next page"
            >
              <ChevronRight />
            </Button>
          </li>
        </ul>
      )}
    </nav>
  )
}
