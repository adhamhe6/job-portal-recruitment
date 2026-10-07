import { FileText, Info } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Alert } from '@/components/ui/alert'
import { InlineError } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Textarea } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Skeleton } from '@/components/ui/skeleton'
import { useApplyToJob } from '@/features/applications/api/applications'
import { useMyResumes } from '@/features/resumes/api/resumes'
import { ApiError, type JobPublic, type JobDetail } from '@/lib/api'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'

const MAX_COVER_LETTER = 8000

function applyErrorMessage(e: unknown): { message: string; field?: boolean } {
  if (e instanceof ApiError) {
    switch (e.code) {
      case 'APPLICATION_ALREADY_EXISTS':
        return {
          message: 'You have already applied to this job. You can follow its progress under Applications.',
        }
      case 'JOB_NOT_ACCEPTING_APPLICATIONS':
        return { message: `${e.message}. This job can no longer be applied to.` }
      case 'JOB_NOT_FOUND':
        return { message: 'This job is no longer available.' }
      case 'RESUME_NOT_FOUND':
        return { message: 'That résumé could not be found. Please choose another one.' }
      case 'VALIDATION_ERROR': {
        const first = e.fieldIssues[0]
        return {
          message: first ? `${first.field ? `${first.field}: ` : ''}${first.message}` : e.message,
          field: true,
        }
      }
      default:
        return { message: e.message }
    }
  }
  return { message: 'Something went wrong while submitting your application. Please try again.' }
}

/**
 * Apply flow: choose a résumé (GET /resumes), optional cover letter, submit (POST /applications).
 * Handles: no résumé / endpoint unavailable (friendly prompt to upload one), already applied (409),
 * job closed (422) and generic failures, all with plain-language messages.
 */
export function ApplyDialog({
  job,
  open,
  onOpenChange,
}: {
  job: JobPublic | JobDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const resumes = useMyResumes(open)
  const apply = useApplyToJob()
  const [coverLetter, setCoverLetter] = useState('')
  const [chosen, setChosen] = useState<string | null>(null)
  const [error, setError] = useState<ReturnType<typeof applyErrorMessage> | null>(null)

  const list = resumes.data ?? []
  const defaultResume = list.find((r) => r.is_primary)?.id ?? list[0]?.id ?? null
  const resumeId = chosen ?? defaultResume
  const tooLong = coverLetter.length > MAX_COVER_LETTER

  const submit = async () => {
    setError(null)
    try {
      const app = await apply.mutateAsync({
        job_id: job.id,
        resume_id: resumeId,
        cover_letter: coverLetter.trim() || null,
        source: 'DIRECT',
      })
      onOpenChange(false)
      toast.success(`Application sent to ${job.company.name}`, {
        description: job.title,
        action: { label: 'View', onClick: () => navigate(paths.application(app.id)) },
      })
    } catch (e) {
      setError(applyErrorMessage(e))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !apply.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>Apply to {job.title}</DialogTitle>
          <DialogDescription>
            {job.company.name}
            {job.location ? ` · ${job.location}` : ''}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-5">
          <section aria-labelledby="resume-heading" className="grid gap-2.5">
            <h3 id="resume-heading" className="text-sm font-medium">
              Résumé
            </h3>
            {resumes.isPending ? (
              <div className="grid gap-2" role="status" aria-label="Loading résumés">
                <Skeleton className="h-14 w-full rounded-lg" />
                <Skeleton className="h-14 w-full rounded-lg" />
              </div>
            ) : resumes.isError ? (
              <InlineError error={resumes.error} />
            ) : list.length === 0 ? (
              <Alert variant="warning" title="Upload a résumé first">
                Recruiters rely on your résumé to evaluate your application.{' '}
                <Link to={paths.resume} onClick={() => onOpenChange(false)}>
                  Upload your résumé
                </Link>{' '}
                and come back — or continue and apply with your profile only.
              </Alert>
            ) : (
              <RadioGroup value={resumeId ?? ''} onValueChange={setChosen} aria-label="Choose a résumé">
                {list.map((r) => (
                  <label
                    key={r.id}
                    htmlFor={`resume-${r.id}`}
                    className="flex cursor-pointer items-center gap-3 rounded-lg border bg-card p-3 transition-colors hover:bg-accent/40 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary-soft/40 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring"
                  >
                    <RadioGroupItem id={`resume-${r.id}`} value={r.id} />
                    <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {r.original_filename ?? 'Résumé'}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {r.is_primary ? 'Primary' : 'Uploaded'}
                        {r.created_at ? ` · ${dates.date(r.created_at)}` : ''}
                      </span>
                    </span>
                  </label>
                ))}
              </RadioGroup>
            )}
          </section>

          <Field
            label="Cover letter"
            optional
            hint="Tell the team why you're a good fit. Plain text."
            error={tooLong ? `Keep it under ${MAX_COVER_LETTER.toLocaleString()} characters` : undefined}
          >
            <Textarea
              rows={6}
              value={coverLetter}
              onChange={(e) => setCoverLetter(e.target.value)}
              placeholder="Hi team — I'm excited about this role because…"
            />
          </Field>
          <p className="-mt-3 text-right text-xs text-muted-foreground tabular" aria-live="off">
            {coverLetter.length.toLocaleString()} / {MAX_COVER_LETTER.toLocaleString()}
          </p>

          {error && (
            <Alert variant="danger">
              {error.message}
              {error.message.startsWith('You have already applied') && (
                <>
                  {' '}
                  <Link to={paths.applications} onClick={() => onOpenChange(false)}>
                    View my applications
                  </Link>
                </>
              )}
            </Alert>
          )}

          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Your application, résumé and profile are shared with {job.company.name}. You can withdraw before
            you're shortlisted.
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={apply.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} loading={apply.isPending} disabled={tooLong || resumes.isPending}>
            Submit application
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
