import { CheckCircle2, Circle } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { paths } from '@/routes/paths'
import { Link } from 'react-router-dom'
import type { ProfileCompletion } from '../lib/types'

/** Where each completion item is fixed (in-page anchor on /profile, or the résumé page). */
export const COMPLETION_TARGETS: Record<string, string> = {
  headline: '#basics',
  summary: '#basics',
  location: '#basics',
  years_experience: '#basics',
  skills: '#skills',
  experience: '#experience',
  education: '#education',
  resume: paths.resume,
  links: '#basics',
  preferences: '#basics',
}

export function CompletionCard({ completion }: { completion: ProfileCompletion }) {
  return (
    <Card aria-labelledby="completion-title">
      <CardHeader>
        <CardTitle id="completion-title" className="text-lg">
          Profile completeness
        </CardTitle>
        <CardDescription>A complete profile ranks higher in matches and searches.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="space-y-2">
          <p className="text-3xl font-semibold tabular">{completion.percent}%</p>
          <Progress value={completion.percent} label="Profile completeness" />
        </div>
        <ul className="grid gap-1.5 text-sm" aria-label="Profile checklist">
          {completion.items.map((item) => {
            const to = COMPLETION_TARGETS[item.key]
            const content = (
              <>
                {item.done ? (
                  <CheckCircle2
                    className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400"
                    aria-hidden
                  />
                ) : (
                  <Circle className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                )}
                <span className={item.done ? 'text-muted-foreground line-through' : ''}>{item.label}</span>
                <span className="sr-only">{item.done ? '(done)' : '(to do)'}</span>
              </>
            )
            return (
              <li key={item.key}>
                {!item.done && to ? (
                  to.startsWith('#') ? (
                    <a href={to} className="flex items-center gap-2 rounded-sm hover:text-primary">
                      {content}
                    </a>
                  ) : (
                    <Link to={to} className="flex items-center gap-2 rounded-sm hover:text-primary">
                      {content}
                    </Link>
                  )
                ) : (
                  <span className="flex items-center gap-2">{content}</span>
                )}
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
