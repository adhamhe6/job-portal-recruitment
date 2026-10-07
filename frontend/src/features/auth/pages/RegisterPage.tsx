import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { PasswordInput, PasswordRules } from '@/components/common/PasswordInput'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { safeRedirect } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useAuth } from '../hooks/useAuth'
import { registerSchema, type RegisterValues } from '../lib/schemas'

const FIELDS = ['first_name', 'last_name', 'email', 'phone', 'password', 'confirm_password'] as const

export default function RegisterPage() {
  useDocumentTitle('Create your account')
  const { registerCandidate } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      first_name: '',
      last_name: '',
      email: '',
      phone: '',
      password: '',
      confirm_password: '',
    },
  })
  const password = useWatch({ control, name: 'password' })

  const onSubmit = handleSubmit(
    async (v) => {
      setFormError(null)
      try {
        const me = await registerCandidate({
          first_name: v.first_name,
          last_name: v.last_name,
          email: v.email,
          password: v.password,
          phone: v.phone || null,
        })
        toast.success(`Welcome to TalentLens, ${me.first_name}!`)
        navigate(safeRedirect(params.get('next'), paths.dashboard), { replace: true })
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, { fields: FIELDS, codeFields: { EMAIL_ALREADY_REGISTERED: 'email' } }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Create your candidate account</h1>
        <p className="text-sm text-muted-foreground">
          Upload your résumé once and get matched to jobs with clear explanations.
        </p>
      </div>
      {formError && <Alert variant="danger">{formError}</Alert>}
      <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Create candidate account">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First name" error={errors.first_name?.message} required>
            <Input autoComplete="given-name" {...register('first_name')} />
          </Field>
          <Field label="Last name" error={errors.last_name?.message} required>
            <Input autoComplete="family-name" {...register('last_name')} />
          </Field>
        </div>
        <Field label="Email" error={errors.email?.message} required>
          <Input
            type="email"
            autoComplete="email"
            inputMode="email"
            placeholder="you@example.com"
            {...register('email')}
          />
        </Field>
        <Field label="Phone" error={errors.phone?.message} optional>
          <Input type="tel" autoComplete="tel" placeholder="+49 30 1234567" {...register('phone')} />
        </Field>
        <Field label="Password" error={errors.password?.message} required>
          <PasswordInput autoComplete="new-password" {...register('password')} />
        </Field>
        <PasswordRules value={password ?? ''} />
        <Field label="Confirm password" error={errors.confirm_password?.message} required>
          <PasswordInput autoComplete="new-password" {...register('confirm_password')} />
        </Field>
        <Button type="submit" size="lg" loading={isSubmitting}>
          Create account
        </Button>
      </form>
      <div className="space-y-2 text-center text-sm text-muted-foreground">
        <p>
          Already have an account?{' '}
          <Link to={paths.login} className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </p>
        <p>
          Hiring?{' '}
          <Link to={paths.registerEmployer} className="font-medium text-primary hover:underline">
            Register your company
          </Link>
        </p>
      </div>
    </div>
  )
}
