import { cn } from '@/lib/utils'

/**
 * Renders user-authored multi-paragraph text safely (no HTML): blank lines split paragraphs, lines starting with
 * "-", "*" or "•" become a bullet list. Used for job descriptions, responsibilities, cover letters.
 */
export function TextBlock({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text?.trim()) return null
  const blocks = text
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean)
  return (
    <div className={cn('space-y-3 text-[15px] leading-relaxed text-foreground/90', className)}>
      {blocks.map((block, i) => {
        const lines = block.split('\n').map((l) => l.trim()).filter(Boolean)
        const isList = lines.length > 0 && lines.every((l) => /^([-*•]|\d+[.)])\s+/.test(l))
        if (isList) {
          const ordered = /^\d+[.)]/.test(lines[0] ?? '')
          const Tag = ordered ? 'ol' : 'ul'
          return (
            <Tag key={i} className={cn('space-y-1.5 pl-5', ordered ? 'list-decimal' : 'list-disc')}>
              {lines.map((l, j) => (
                <li key={j} className="pl-1 marker:text-muted-foreground">
                  {l.replace(/^([-*•]|\d+[.)])\s+/, '')}
                </li>
              ))}
            </Tag>
          )
        }
        return (
          <p key={i} className="whitespace-pre-line">
            {block}
          </p>
        )
      })}
    </div>
  )
}
