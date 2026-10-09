import { zodResolver } from '@hookform/resolvers/zod'
import { Lock, MessageSquareText, Pencil, Star } from 'lucide-react'
import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { EmptyState, ErrorState } from '@/components/common/States'
import { TextBlock } from '@/components/common/TextBlock'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { NativeSelect, Textarea } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { dates, fmt } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useInterviewFeedback, useSaveFeedback } from '../api/interviews'
import { RECOMMENDATIONS, type FeedbackOut, type HireRecommendation } from '../api/types'
import {
  emptyFeedback,
  feedbackSchema,
  feedbackToValues,
  toFeedbackPayload,
  type FeedbackFormValues,
} from '../lib/feedback'
import { RATING_LABELS, RECOMMENDATION_LABELS, RECOMMENDATION_OPTIONS } from '../lib/labels'

const RECOMMENDATION_TONE: Record<HireRecommendation, 'success' | 'info' | 'warning' | 'danger'> = {
  STRONG_HIRE: 'success',
  HIRE: 'info',
  NO_HIRE: 'warning',
  STRONG_NO_HIRE: 'danger',
}

function RatingStars({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-1.5" role="img" aria-label={`Rating ${value} out of 5`}>
      <span className="inline-flex" aria-hidden>
        {[1, 2, 3, 4, 5].map((n) => (
          <Star
            key={n}
            className={cn('size-4', n <= value ? 'fill-amber-400 text-amber-500' : 'text-muted-foreground/40')}
          />
        ))}
      </span>
      <span className="text-sm font-medium tabular" aria-hidden>
        {value}/5
      </span>
    </span>
  )
}

function FeedbackForm({
  interviewId,
  existing,
  onDone,
  onCancel,
}: {
  interviewId: string
  existing?: FeedbackOut
  onDone: () => void
  onCancel?: () => void
}) {
  const save = useSaveFeedback(interviewId)
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors },
  } = useForm<FeedbackFormValues>({
    resolver: zodResolver(feedbackSchema),
    defaultValues: existing ? feedbackToValues(existing) : emptyFeedback,
    mode: 'onTouched',
  })

  const onSubmit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        await save.mutateAsync({ values: toFeedbackPayload(values), existing: Boolean(existing) })
        toast.success(existing ? 'Feedback updated' : 'Feedback submitted')
        onDone()
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, {
            fields: ['rating', 'recommendation', 'strengths', 'weaknesses', 'notes'],
          }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <form onSubmit={onSubmit} noValidate className="grid gap-4">
      {formError && <Alert variant="danger">{formError}</Alert>}
      <Controller
        control={control}
        name="rating"
        render={({ field }) => (
          <fieldset className="grid gap-1.5">
            <legend className="mb-1.5 text-sm font-medium">
              Overall rating
              <span className="ml-0.5 text-destructive" aria-hidden>
                *
              </span>
            </legend>
            <RadioGroup
              value={field.value}
              onValueChange={field.onChange}
              onBlur={field.onBlur}
              aria-label="Overall rating"
              aria-invalid={errors.rating ? true : undefined}
              className="flex flex-wrap gap-2"
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <label
                  key={n}
                  htmlFor={`rating-${n}`}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm transition-colors hover:bg-accent/40 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary-soft/40 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring"
                >
                  <RadioGroupItem id={`rating-${n}`} value={String(n)} />
                  <span>
                    <span className="font-semibold">{n}</span>{' '}
                    <span className="text-muted-foreground">{RATING_LABELS[n]}</span>
                  </span>
                </label>
              ))}
            </RadioGroup>
            {errors.rating && (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.rating.message}
              </p>
            )}
          </fieldset>
        )}
      />
      <Field label="Recommendation" required error={errors.recommendation?.message}>
        <NativeSelect {...register('recommendation')}>
          <option value="">Choose a recommendation…</option>
          {RECOMMENDATION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Strengths" optional error={errors.strengths?.message}>
        <Textarea rows={3} maxLength={4000} {...register('strengths')} />
      </Field>
      <Field label="Concerns / weaknesses" optional error={errors.weaknesses?.message}>
        <Textarea rows={3} maxLength={4000} {...register('weaknesses')} />
      </Field>
      <Field label="Additional notes" optional error={errors.notes?.message}>
        <Textarea rows={3} maxLength={4000} {...register('notes')} />
      </Field>
      <div className="flex flex-wrap justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={save.isPending}>
            Cancel
          </Button>
        )}
        <Button type="submit" loading={save.isPending}>
          {existing ? 'Update feedback' : 'Submit feedback'}
        </Button>
      </div>
    </form>
  )
}

function FeedbackItem({ item, onEdit }: { item: FeedbackOut; onEdit?: () => void }) {
  return (
    <li className="space-y-2 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          {item.author_name}
          {item.is_mine && <span className="ml-2 text-xs font-normal text-muted-foreground">(you)</span>}
        </p>
        <div className="flex items-center gap-3">
          <RatingStars value={item.rating} />
          <Badge variant={RECOMMENDATION_TONE[item.recommendation]}>
            {RECOMMENDATION_LABELS[item.recommendation]}
          </Badge>
        </div>
      </div>
      {item.strengths && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Strengths</p>
          <TextBlock text={item.strengths} className="text-sm" />
        </div>
      )}
      {item.weaknesses && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Concerns</p>
          <TextBlock text={item.weaknesses} className="text-sm" />
        </div>
      )}
      {item.notes && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Notes</p>
          <TextBlock text={item.notes} className="text-sm" />
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <p className="text-xs text-muted-foreground">Submitted {dates.dateTime(item.submitted_at)}</p>
        {onEdit && (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            <Pencil /> Edit my feedback
          </Button>
        )}
      </div>
    </li>
  )
}

/**
 * Internal interview feedback (staff only — the backend refuses candidates). Shows the aggregate, every entry, and
 * the form to add or edit the current user's own entry.
 */
export function FeedbackSection({
  interviewId,
  canSubmit,
  blockedReason,
  mayWrite,
}: {
  interviewId: string
  /** The API says this user may submit now (staff, no entry yet, interview started). */
  canSubmit: boolean
  /** Why submitting is not possible right now, if known. */
  blockedReason: string | null
  /** The user's role can write feedback at all (recruiters, hiring managers) — admins only read. */
  mayWrite: boolean
}) {
  const feedback = useInterviewFeedback(interviewId, true)
  const [editing, setEditing] = useState(false)
  const data = feedback.data
  const mine = data?.items.find((i) => i.is_mine)
  const showNewForm = canSubmit && !mine

  return (
    <Card id="feedback" aria-labelledby="feedback-heading">
      <CardHeader>
        <CardTitle id="feedback-heading" className="flex items-center gap-2 text-lg">
          <MessageSquareText className="size-5 text-muted-foreground" aria-hidden /> Interview feedback
        </CardTitle>
        <CardDescription className="flex items-center gap-1.5">
          <Lock className="size-3.5" aria-hidden /> Internal to the hiring team — candidates can never see it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {feedback.isPending ? (
          <div className="space-y-3" role="status" aria-busy="true" aria-label="Loading feedback">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : feedback.isError ? (
          <ErrorState compact error={feedback.error} onRetry={() => feedback.refetch()} />
        ) : (
          <>
            {data && data.count > 0 && (
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg bg-muted/50 px-4 py-3 text-sm">
                <p>
                  <span className="text-muted-foreground">Average rating </span>
                  <strong className="tabular">{fmt.num(data.average_rating)}/5</strong>
                  <span className="text-muted-foreground"> from {data.count} {data.count === 1 ? 'entry' : 'entries'}</span>
                </p>
                <ul className="flex flex-wrap gap-2" aria-label="Recommendations">
                  {RECOMMENDATIONS.filter((r) => (data.recommendations[r] ?? 0) > 0).map((r) => (
                    <li key={r}>
                      <Badge variant={RECOMMENDATION_TONE[r]}>
                        {RECOMMENDATION_LABELS[r]}: {data.recommendations[r]}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {showNewForm && (
              <section aria-labelledby="my-feedback-heading" className="rounded-lg border border-primary/30 p-4">
                <h3 id="my-feedback-heading" className="mb-3 font-semibold">
                  Your feedback
                </h3>
                <FeedbackForm interviewId={interviewId} onDone={() => undefined} />
              </section>
            )}
            {!showNewForm && !mine && mayWrite && blockedReason && (
              <Alert variant="info">{blockedReason}</Alert>
            )}
            {!mayWrite && (
              <p className="text-sm text-muted-foreground">
                Interviewers and hiring managers write the feedback; you can read all entries here.
              </p>
            )}

            {data && data.items.length === 0 ? (
              <EmptyState
                compact
                icon={<MessageSquareText aria-hidden />}
                title="No feedback yet"
                description="Feedback appears here as soon as an interviewer submits it."
              />
            ) : (
              <ul className="space-y-3" aria-label="Feedback entries">
                {data?.items.map((item) =>
                  item.is_mine && editing ? (
                    <li key={item.id} className="rounded-lg border border-primary/30 p-4">
                      <h3 className="mb-3 font-semibold">Edit your feedback</h3>
                      <FeedbackForm
                        interviewId={interviewId}
                        existing={item}
                        onDone={() => setEditing(false)}
                        onCancel={() => setEditing(false)}
                      />
                    </li>
                  ) : (
                    <FeedbackItem
                      key={item.id}
                      item={item}
                      onEdit={item.is_mine && mayWrite ? () => setEditing(true) : undefined}
                    />
                  ),
                )}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
