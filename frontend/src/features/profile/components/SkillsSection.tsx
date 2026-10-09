import { zodResolver } from '@hookform/resolvers/zod'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { EmptyState } from '@/components/common/States'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect } from '@/components/ui/input'
import { SkillPicker, type PickedSkill } from '@/features/skills/components/SkillPicker'
import { errorMessage } from '@/lib/api'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { useSkillMutations } from '../api/profile'
import {
  labelOf,
  PROFICIENCY_OPTIONS,
  skillBody,
  skillDefaults,
  skillSchema,
  type SkillValues,
} from '../lib/forms'
import type { CandidateSkill } from '../lib/types'
import { EntryDialog, EntryRow, SectionCard } from './Section'

type Target = { kind: 'new'; skill: PickedSkill } | { kind: 'edit'; item: CandidateSkill }

function SkillDialog({ target, onClose }: { target: Target; onClose: () => void }) {
  const { add, update } = useSkillMutations()
  const [formError, setFormError] = useState<string | null>(null)
  const item = target.kind === 'edit' ? target.item : undefined
  const name = target.kind === 'edit' ? target.item.skill.name : target.skill.name
  const form = useForm<SkillValues>({
    resolver: zodResolver(skillSchema),
    defaultValues: skillDefaults(item),
    mode: 'onTouched',
  })
  const { register, handleSubmit, setError, formState } = form
  const { errors } = formState

  const submit = handleSubmit(
    async (values) => {
      setFormError(null)
      try {
        const body = skillBody(values)
        if (target.kind === 'edit') {
          // Editing a suggested skill also confirms it.
          await update.mutateAsync({
            id: target.item.id,
            body: { ...body, status: target.item.status === 'SUGGESTED' ? 'CONFIRMED' : undefined },
          })
        } else {
          await add.mutateAsync({
            ...(target.skill.id ? { skill_id: target.skill.id } : { name: target.skill.name }),
            ...body,
          })
        }
        toast.success(target.kind === 'edit' ? `${name} updated` : `${name} added to your profile`)
        onClose()
      } catch (e) {
        setFormError(applyApiErrors(e, setError, { fields: ['proficiency', 'years_experience'] }))
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <EntryDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={target.kind === 'edit' ? `Edit ${name}` : `Add ${name}`}
      description="How well do you know this skill? Both fields are optional but improve your matches."
      onSubmit={submit}
      pending={add.isPending || update.isPending}
      error={formError}
    >
      <Field label="Proficiency" optional error={errors.proficiency?.message}>
        <NativeSelect {...register('proficiency')}>
          <option value="">Not specified</option>
          {PROFICIENCY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Years of experience" optional error={errors.years_experience?.message}>
        <Input inputMode="decimal" placeholder="e.g. 3.5" {...register('years_experience')} />
      </Field>
    </EntryDialog>
  )
}

export function SkillsSection({ items }: { items: CandidateSkill[] }) {
  const { update, remove } = useSkillMutations()
  const [target, setTarget] = useState<Target | null>(null)
  const [toDelete, setToDelete] = useState<CandidateSkill | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const confirmed = items.filter((s) => s.status === 'CONFIRMED')
  const suggested = items.filter((s) => s.status === 'SUGGESTED')

  const decide = async (s: CandidateSkill, status: 'CONFIRMED' | 'REJECTED') => {
    try {
      await update.mutateAsync({ id: s.id, body: { status } })
      toast.success(
        status === 'CONFIRMED' ? `${s.skill.name} added to your skills` : `${s.skill.name} dismissed`,
      )
    } catch (e) {
      toast.error(`Could not update ${s.skill.name}`, { description: errorMessage(e) })
    }
  }

  const doDelete = async () => {
    if (!toDelete) return
    setDeleteError(null)
    try {
      await remove.mutateAsync(toDelete.id)
      toast.success(`${toDelete.skill.name} removed`)
      setToDelete(null)
    } catch (e) {
      setDeleteError(errorMessage(e))
    }
  }

  return (
    <SectionCard
      id="skills"
      title="Skills"
      description="Search the skill library, then set your proficiency and years of experience."
    >
      <div className="grid gap-5">
        <div className="grid gap-1.5">
          <label htmlFor="skill-search" className="text-sm font-medium">
            Add a skill
          </label>
          <SkillPicker
            id="skill-search"
            selected={items
              .filter((s) => s.status !== 'REJECTED')
              .map((s) => ({ id: s.skill.id, name: s.skill.name }))}
            onAdd={(skill) => setTarget({ kind: 'new', skill })}
            allowCreate
            placeholder="Search skills (e.g. Python)…"
          />
        </div>

        {suggested.length > 0 && (
          <section
            aria-labelledby="suggested-skills"
            className="rounded-lg border border-dashed bg-surface p-3"
          >
            <h4 id="suggested-skills" className="text-sm font-semibold">
              Suggested from your résumé
            </h4>
            <p className="mb-2 text-xs text-muted-foreground">
              Nothing is added to your profile until you confirm it.
            </p>
            <ul className="divide-y">
              {suggested.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0 truncate text-sm font-medium">{s.skill.name}</span>
                  <span className="flex shrink-0 gap-1.5">
                    <Button
                      size="sm"
                      variant="soft"
                      onClick={() => decide(s, 'CONFIRMED')}
                      aria-label={`Confirm ${s.skill.name}`}
                    >
                      <Check /> Confirm
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => decide(s, 'REJECTED')}
                      aria-label={`Dismiss ${s.skill.name}`}
                    >
                      <X /> Dismiss
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {confirmed.length === 0 ? (
          <EmptyState
            compact
            title="No skills yet"
            description="Add at least three skills — they carry the most weight in job matching."
          />
        ) : (
          <ul className="divide-y" aria-label="Your skills">
            {confirmed.map((s) => (
              <EntryRow
                key={s.id}
                label={s.skill.name}
                title={s.skill.name}
                badge={s.source === 'RESUME' ? <Badge variant="info">From résumé</Badge> : null}
                meta={
                  [
                    labelOf(PROFICIENCY_OPTIONS, s.proficiency),
                    s.years_experience != null ? `${Number(s.years_experience)} yrs` : '',
                  ]
                    .filter(Boolean)
                    .join(' · ') || 'No proficiency set'
                }
                onEdit={() => setTarget({ kind: 'edit', item: s })}
                onDelete={() => {
                  setDeleteError(null)
                  setToDelete(s)
                }}
              />
            ))}
          </ul>
        )}
      </div>

      {target && (
        <SkillDialog
          key={target.kind === 'edit' ? target.item.id : (target.skill.id ?? target.skill.name)}
          target={target}
          onClose={() => setTarget(null)}
        />
      )}
      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Remove this skill?"
        description={`${toDelete?.skill.name ?? ''} will be removed from your profile and no longer count towards your matches.`}
        confirmLabel="Remove"
        destructive
        loading={remove.isPending}
        onConfirm={doDelete}
      >
        {deleteError && (
          <p role="alert" className="text-sm text-destructive">
            {deleteError}
          </p>
        )}
      </ConfirmDialog>
    </SectionCard>
  )
}
