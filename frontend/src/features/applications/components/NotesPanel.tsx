import { StickyNote } from 'lucide-react'
import { useState } from 'react'
import { EmptyState, ErrorState } from '@/components/common/States'
import { TextBlock } from '@/components/common/TextBlock'
import { Alert } from '@/components/ui/alert'
import { Avatar } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api'
import { dates } from '@/lib/format'
import { useAddNote, useApplicationNotes } from '../api/applications'

const MAX = 4000

/** Internal notes: visible to the hiring team only. Never rendered (nor requested) for candidates. */
export function NotesPanel({ applicationId }: { applicationId: string }) {
  const notes = useApplicationNotes(applicationId, true)
  const add = useAddNote(applicationId)
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const text = body.trim()
    if (!text) {
      setError('Write a note before saving.')
      return
    }
    setError(null)
    add.mutate(text, {
      onSuccess: () => setBody(''),
      onError: (err) => setError(errorMessage(err, "Couldn't save the note. Please try again.")),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <StickyNote className="size-4 text-primary" aria-hidden /> Internal notes
        </CardTitle>
        <CardDescription>Only your hiring team can see these. Candidates never do.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form onSubmit={submit} className="space-y-2" noValidate>
          <Field label="Add a note" error={error}>
            <Textarea
              rows={3}
              maxLength={MAX}
              value={body}
              onChange={(e) => {
                setBody(e.target.value)
                if (error) setError(null)
              }}
              placeholder="Impressions from the screen, concerns, next steps…"
            />
          </Field>
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground tabular" aria-hidden>
              {body.length}/{MAX}
            </span>
            <Button type="submit" size="sm" loading={add.isPending}>
              Add note
            </Button>
          </div>
        </form>

        {notes.isPending ? (
          <div className="space-y-3" role="status" aria-label="Loading notes">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : notes.isError ? (
          <ErrorState
            error={notes.error}
            onRetry={() => notes.refetch()}
            compact
            title="Couldn't load notes"
          />
        ) : notes.data.length === 0 ? (
          <EmptyState
            className="py-6"
            title="No notes yet"
            description="Capture screening impressions so the rest of the team stays aligned."
          />
        ) : (
          <ul className="space-y-4" aria-label="Notes">
            {notes.data.map((n) => (
              <li key={n.id} className="flex gap-3">
                <Avatar name={n.author_name ?? '?'} size="sm" />
                <div className="min-w-0 flex-1 rounded-lg bg-surface p-3">
                  <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {n.author_name ?? 'Former team member'}
                    </span>
                    <time dateTime={n.created_at} title={dates.dateTime(n.created_at)}>
                      {dates.relative(n.created_at)}
                    </time>
                  </p>
                  <TextBlock text={n.body} className="mt-1 text-sm" />
                </div>
              </li>
            ))}
          </ul>
        )}
        {add.isError && !error && <Alert variant="danger">{errorMessage(add.error)}</Alert>}
      </CardContent>
    </Card>
  )
}
