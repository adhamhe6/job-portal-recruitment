import { zodResolver } from '@hookform/resolvers/zod'
import { AlertTriangle, CheckCheck, Pencil, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { ErrorState } from '@/components/common/States'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Field } from '@/components/ui/field'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { EntryDialog } from '@/features/profile/components/Section'
import { useProfile } from '@/features/profile/api/profile'
import { EDUCATION_LEVEL_LABELS } from '@/lib/enums'
import { ApiError, errorMessage } from '@/lib/api'
import { dates } from '@/lib/format'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { cn } from '@/lib/utils'
import {
  useApplyExtracted,
  useExtracted,
  usePatchExtracted,
  type ApplyResult,
  type ExtractedPatch,
  type ExtractedResume,
  type ProfileField,
  type ResumeOut,
} from '../api/resumes'
import {
  applySummary,
  blocker,
  confidenceLabel,
  defaultSelection,
  effectiveSelection,
  LIST_SECTIONS,
  sameValue,
  scalarSuggestions,
  sectionLabel,
  selectionCount,
  skipText,
  toApplyRequest,
  type ListSection,
  type ScalarSuggestion,
  type Selection,
  type Suggestion,
} from '../lib/review'
import { SuggestionEditDialog, type EditTarget } from './SuggestionEditDialog'

const SECTION_TITLES: Record<ListSection, string> = {
  skills: 'Skills',
  experiences: 'Work experience',
  educations: 'Education',
  certifications: 'Certifications',
  languages: 'Languages',
}

function suggestionName(section: ListSection, item: Suggestion): string {
  switch (section) {
    case 'skills':
      return (item as { name: string }).name
    case 'experiences': {
      const e = item as { title?: string | null; company?: string | null }
      return [e.title, e.company].filter(Boolean).join(' at ') || 'Untitled role'
    }
    case 'educations': {
      const e = item as { institution?: string | null; degree?: string | null }
      return e.institution || e.degree || 'Unnamed education'
    }
    case 'certifications':
      return (item as { name: string }).name
    case 'languages':
      return (item as { language: string }).language
  }
}

function suggestionDetail(section: ListSection, item: Suggestion): string {
  switch (section) {
    case 'skills': {
      const s = item as { listed: boolean }
      return s.listed ? 'Found in your skills list' : 'Mentioned in your experience'
    }
    case 'experiences': {
      const e = item as {
        location?: string | null
        start_date?: string | null
        end_date?: string | null
        is_current: boolean
      }
      const range = e.start_date
        ? `${dates.date(e.start_date)} – ${e.is_current ? 'Present' : e.end_date ? dates.date(e.end_date) : '—'}`
        : ''
      return [range, e.location].filter(Boolean).join(' · ')
    }
    case 'educations': {
      const e = item as {
        degree?: string | null
        degree_level?: keyof typeof EDUCATION_LEVEL_LABELS | null
        field_of_study?: string | null
        start_year?: number | null
        end_year?: number | null
      }
      return [
        e.degree,
        e.degree_level ? EDUCATION_LEVEL_LABELS[e.degree_level] : null,
        e.field_of_study,
        e.start_year || e.end_year ? `${e.start_year ?? ''}–${e.end_year ?? ''}` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    }
    case 'certifications': {
      const c = item as { issuer?: string | null; issued_on?: string | null; issued_year?: number | null }
      return [c.issuer, c.issued_on ? dates.date(c.issued_on) : c.issued_year].filter(Boolean).join(' · ')
    }
    case 'languages': {
      const l = item as { proficiency?: string | null }
      return l.proficiency ? l.proficiency.charAt(0) + l.proficiency.slice(1).toLowerCase() : ''
    }
  }
}

function SuggestionRow({
  section,
  item,
  checked,
  onToggle,
  onEdit,
  onReject,
  busy,
}: {
  section: ListSection
  item: Suggestion
  checked: boolean
  onToggle: () => void
  onEdit: () => void
  onReject: () => void
  busy: boolean
}) {
  const name = suggestionName(section, item)
  const detail = suggestionDetail(section, item)
  const blocked = blocker(section, item)
  const conf = confidenceLabel(item.confidence)
  const id = `sx-${section}-${item.index}`
  return (
    <li className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
      <Checkbox
        id={id}
        checked={checked && !blocked}
        disabled={Boolean(blocked)}
        onCheckedChange={onToggle}
        aria-describedby={`${id}-meta`}
        className="mt-0.5"
      />
      <div className="min-w-0 flex-1 space-y-1">
        <label
          htmlFor={id}
          className={cn('block cursor-pointer font-medium break-words', blocked && 'cursor-default')}
        >
          {name}
        </label>
        {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
        <p id={`${id}-meta`} className="flex flex-wrap items-center gap-1.5 text-xs">
          <Badge variant={conf.variant}>{conf.label}</Badge>
          {item.corrected && <Badge variant="info">Edited by you</Badge>}
          {blocked && (
            <span className="inline-flex items-center gap-1 text-amber-800 dark:text-amber-300">
              <AlertTriangle className="size-3.5" aria-hidden /> {blocked}
            </span>
          )}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onEdit}
          disabled={busy}
          aria-label={`Edit suggestion ${name}`}
        >
          <Pencil />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onReject}
          disabled={busy}
          aria-label={`Reject suggestion ${name}`}
        >
          <X />
        </Button>
      </div>
    </li>
  )
}

// --- scalar (profile field) suggestions ------------------------------------------------------------------------------

const SCALAR_SCHEMAS: Record<ProfileField, z.ZodType<string>> = {
  headline: z.string().trim().max(200, 'Must be at most 200 characters'),
  summary: z.string().trim().max(5000, 'Must be at most 5,000 characters'),
  years_experience: z
    .string()
    .trim()
    .refine(
      (v) => v === '' || (/^\d+(\.\d)?$/.test(v) && Number(v) <= 70),
      'Enter a number between 0 and 70',
    ),
  location: z.string().trim().max(200, 'Must be at most 200 characters'),
  phone: z.string().trim().max(32, 'Must be at most 32 characters'),
  linkedin_url: z
    .string()
    .trim()
    .max(500)
    .refine((v) => v === '' || /^https?:\/\/\S+$/i.test(v), 'Must start with http:// or https://'),
  github_url: z
    .string()
    .trim()
    .max(500)
    .refine((v) => v === '' || /^https?:\/\/\S+$/i.test(v), 'Must start with http:// or https://'),
  portfolio_url: z
    .string()
    .trim()
    .max(500)
    .refine((v) => v === '' || /^https?:\/\/\S+$/i.test(v), 'Must start with http:// or https://'),
}

function scalarPatch(field: ProfileField, value: string): ExtractedPatch {
  const v = value.trim() === '' ? null : value.trim()
  switch (field) {
    case 'headline':
      return { headline: v }
    case 'summary':
      return { summary: v }
    case 'years_experience':
      return { years_of_experience: v === null ? null : Number(v) }
    case 'location':
    case 'phone':
    case 'linkedin_url':
    case 'github_url':
    case 'portfolio_url':
      return { contact: { [field]: v } }
  }
}

function ScalarEditDialog({
  row,
  onClose,
  save,
}: {
  row: ScalarSuggestion
  onClose: () => void
  save: (patch: ExtractedPatch) => Promise<void>
}) {
  const schema = useMemo(() => z.object({ value: SCALAR_SCHEMAS[row.field] }), [row.field])
  const form = useForm<{ value: string }>({
    resolver: zodResolver(schema),
    defaultValues: { value: row.suggested },
    mode: 'onTouched',
  })
  const [pending, setPending] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const submit = form.handleSubmit(
    async ({ value }) => {
      setPending(true)
      setFormError(null)
      try {
        await save(scalarPatch(row.field, value))
        onClose()
      } catch (e) {
        setFormError(
          applyApiErrors(e, form.setError, {
            fields: ['value'],
            fieldMap: { [row.field]: 'value', [`contact.${row.field}`]: 'value' },
          }),
        )
        focusFirstError()
      } finally {
        setPending(false)
      }
    },
    () => focusFirstError(),
  )
  const multiline = row.field === 'summary'
  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Edit suggested ${row.label.toLowerCase()}`}
      description="This only changes the suggestion. Your profile is updated when you apply it."
      onSubmit={submit}
      pending={pending}
      error={formError}
    >
      <Field label={row.label} error={form.formState.errors.value?.message}>
        {multiline ? (
          <Textarea rows={6} {...form.register('value')} />
        ) : (
          <Input {...form.register('value')} />
        )}
      </Field>
    </EntryDialog>
  )
}

function ScalarRow({
  row,
  checked,
  overwrite,
  onToggle,
  onToggleOverwrite,
  onEdit,
}: {
  row: ScalarSuggestion
  checked: boolean
  overwrite: boolean
  onToggle: () => void
  onToggleOverwrite: () => void
  onEdit: () => void
}) {
  const conflict = row.current !== '' && !sameValue(row.current, row.suggested)
  const same = row.current !== '' && !conflict
  const id = `sx-field-${row.field}`
  return (
    <li className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[1fr_auto]">
      <div className="flex items-start gap-3">
        <Checkbox
          id={id}
          checked={checked && !same}
          disabled={same}
          onCheckedChange={onToggle}
          className="mt-0.5"
          aria-describedby={`${id}-meta`}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <label htmlFor={id} className="block cursor-pointer font-medium">
            {row.label}
          </label>
          <p className="text-sm break-words whitespace-pre-line text-foreground/90">{row.suggested}</p>
          <div id={`${id}-meta`} className="space-y-1.5 text-xs text-muted-foreground">
            {same && <p>Already on your profile.</p>}
            {conflict && (
              <p>
                Your profile currently says:{' '}
                <span className="font-medium text-foreground">{row.current}</span>
              </p>
            )}
            {conflict && checked && (
              <label className="flex items-center gap-2 text-foreground">
                <Checkbox checked={overwrite} onCheckedChange={onToggleOverwrite} />
                Replace my current {row.label.toLowerCase()}
              </label>
            )}
            {conflict && !checked && <p>Your current value will be kept unless you select this.</p>}
          </div>
        </div>
      </div>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={onEdit}
        aria-label={`Edit suggested ${row.label.toLowerCase()}`}
        className="justify-self-end"
      >
        <Pencil />
      </Button>
    </li>
  )
}

// --- panel -----------------------------------------------------------------------------------------------------------

function Group({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {title}
        {count !== undefined && <Badge variant="muted">{count}</Badge>}
      </h3>
      {children}
    </section>
  )
}

export function ReviewPanel({ resume, onClose }: { resume: ResumeOut; onClose: () => void }) {
  const extracted = useExtracted(resume.status === 'PROCESSED' ? resume.id : null)
  const profile = useProfile()
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    headingRef.current?.focus()
  }, [resume.id])

  return (
    <Card aria-labelledby="review-title" id="review">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <CardTitle id="review-title" ref={headingRef} tabIndex={-1} className="text-lg outline-none">
            Review suggestions
          </CardTitle>
          <CardDescription>
            What we found in <span className="font-medium break-all">{resume.original_filename}</span>.
            Nothing changes on your profile until you apply the items you choose.
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close review
        </Button>
      </CardHeader>
      <CardContent>
        {resume.status !== 'PROCESSED' ? (
          <Alert variant="info" title="This résumé is not ready yet">
            Suggestions appear here as soon as processing has finished.
          </Alert>
        ) : extracted.isPending ? (
          <div className="grid gap-3" role="status" aria-busy="true" aria-label="Loading suggestions">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : extracted.isError ? (
          <ErrorState
            compact
            error={extracted.error}
            onRetry={() => extracted.refetch()}
            title="Couldn't load the suggestions"
          />
        ) : (
          <ReviewBody
            // Re-seed the default selection when a different résumé is reviewed.
            key={resume.id}
            resume={resume}
            data={extracted.data}
            currentProfile={profile.data}
          />
        )}
      </CardContent>
    </Card>
  )
}

function ReviewBody({
  resume,
  data,
  currentProfile,
}: {
  resume: ResumeOut
  data: ExtractedResume
  currentProfile: ReturnType<typeof useProfile>['data']
}) {
  const patch = usePatchExtracted(resume.id)
  const apply = useApplyExtracted(resume.id)
  const [chosen, setChosen] = useState<Selection | null>(null)
  const [editing, setEditing] = useState<EditTarget | null>(null)
  const [editingScalar, setEditingScalar] = useState<ScalarSuggestion | null>(null)
  const [result, setResult] = useState<ApplyResult | null>(null)
  const [applyError, setApplyError] = useState<string | null>(null)

  const scalars = scalarSuggestions(data, currentProfile)
  const selection = chosen ?? defaultSelection(data, currentProfile)
  const count = selectionCount(effectiveSelection(selection, data))

  const toggleItem = (section: ListSection, index: number) => {
    const list = selection.lists[section]
    setChosen({
      ...selection,
      lists: {
        ...selection.lists,
        [section]: list.includes(index) ? list.filter((i) => i !== index) : [...list, index],
      },
    })
  }
  const toggleField = (field: ProfileField) => {
    const on = selection.fields.includes(field)
    setChosen({
      ...selection,
      fields: on ? selection.fields.filter((f) => f !== field) : [...selection.fields, field],
      overwrite: on ? selection.overwrite.filter((f) => f !== field) : selection.overwrite,
    })
  }
  const toggleOverwrite = (field: ProfileField) =>
    setChosen({
      ...selection,
      overwrite: selection.overwrite.includes(field)
        ? selection.overwrite.filter((f) => f !== field)
        : [...selection.overwrite, field],
    })

  const selectAll = () => setChosen(defaultSelection(data, currentProfile))
  const clear = () =>
    setChosen({
      lists: { skills: [], experiences: [], educations: [], certifications: [], languages: [] },
      fields: [],
      overwrite: [],
    })

  const save = async (p: ExtractedPatch) => {
    await patch.mutateAsync(p)
    toast.success('Suggestion updated')
  }
  const reject = async (section: ListSection, item: Suggestion) => {
    try {
      await patch.mutateAsync({ [section]: [{ index: item.index, remove: true }] })
      toast.success(`Removed “${suggestionName(section, item)}”`, {
        description: 'It will not be offered again for this résumé.',
      })
    } catch (e) {
      toast.error('Could not remove the suggestion', { description: errorMessage(e) })
    }
  }

  const submit = async () => {
    setApplyError(null)
    setResult(null)
    try {
      const body = toApplyRequest(selection, data)
      const res = await apply.mutateAsync(body)
      setResult(res)
      setChosen(null)
      toast.success('Profile updated', { description: applySummary(res) })
    } catch (e) {
      setApplyError(
        e instanceof ApiError && e.code === 'RESUME_NOT_PROCESSED'
          ? 'This résumé is still being processed. Try again in a moment.'
          : errorMessage(e),
      )
    }
  }

  const total = LIST_SECTIONS.reduce((n, s) => n + data[s].length, 0) + scalars.length

  return (
    <div className="grid gap-6">
      {data.warnings.length > 0 && (
        <Alert variant="warning" title="Some parts of your résumé were hard to read">
          <ul>
            {data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      )}

      {result && (
        <Alert variant="success" title={applySummary(result)}>
          {result.skipped.length > 0 && (
            <>
              <p>Skipped:</p>
              <ul>
                {result.skipped.map((s, i) => (
                  <li key={`${s.section}-${s.index ?? 'f'}-${i}`}>
                    {sectionLabel(s.section)}
                    {s.index != null ? ` #${s.index + 1}` : ''}: {skipText(s.reason)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Alert>
      )}
      {applyError && <Alert variant="danger">{applyError}</Alert>}

      {(data.contact.name || data.contact.email) && (
        <p className="rounded-lg bg-surface p-3 text-sm text-muted-foreground">
          Contact found in the résumé:{' '}
          <span className="font-medium text-foreground">
            {[data.contact.name, data.contact.email].filter(Boolean).join(' · ')}
          </span>
          . Your name and email come from your account and are never changed by an import.
        </p>
      )}

      {total === 0 ? (
        <Alert variant="info" title="Nothing to review">
          We could not find structured details in this résumé. You can add everything manually on your
          profile.
        </Alert>
      ) : (
        <>
          {scalars.length > 0 && (
            <Group title="Profile details" count={scalars.length}>
              <ul className="divide-y rounded-lg border p-3" aria-label="Profile detail suggestions">
                {scalars.map((row) => (
                  <ScalarRow
                    key={row.field}
                    row={row}
                    checked={selection.fields.includes(row.field)}
                    overwrite={selection.overwrite.includes(row.field)}
                    onToggle={() => toggleField(row.field)}
                    onToggleOverwrite={() => toggleOverwrite(row.field)}
                    onEdit={() => setEditingScalar(row)}
                  />
                ))}
              </ul>
            </Group>
          )}
          {LIST_SECTIONS.map((section) => {
            const items = data[section] as Suggestion[]
            if (items.length === 0) return null
            return (
              <Group key={section} title={SECTION_TITLES[section]} count={items.length}>
                <ul
                  className="divide-y rounded-lg border p-3"
                  aria-label={`${SECTION_TITLES[section]} suggestions`}
                >
                  {items.map((item) => (
                    <SuggestionRow
                      key={item.index}
                      section={section}
                      item={item}
                      checked={selection.lists[section].includes(item.index)}
                      busy={patch.isPending}
                      onToggle={() => toggleItem(section, item.index)}
                      onEdit={() => setEditing({ section, item } as EditTarget)}
                      onReject={() => reject(section, item)}
                    />
                  ))}
                </ul>
              </Group>
            )
          })}

          <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card/95 p-3 shadow-md backdrop-blur">
            <p className="text-sm" aria-live="polite">
              <span className="font-semibold tabular">{count}</span> selected
              {data.has_corrections && <span className="text-muted-foreground"> · includes your edits</span>}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="ghost" size="sm" onClick={selectAll}>
                Select all applicable
              </Button>
              <Button variant="ghost" size="sm" onClick={clear} disabled={count === 0}>
                Clear
              </Button>
              <Button onClick={submit} loading={apply.isPending} disabled={count === 0}>
                <CheckCheck /> Apply {count > 0 ? `${count} selected` : 'selected'} to my profile
              </Button>
            </div>
          </div>
        </>
      )}

      {editing && <SuggestionEditDialog target={editing} onClose={() => setEditing(null)} save={save} />}
      {editingScalar && (
        <ScalarEditDialog row={editingScalar} onClose={() => setEditingScalar(null)} save={save} />
      )}
    </div>
  )
}
