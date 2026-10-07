import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { PasswordInput, PasswordRules } from '@/components/common/PasswordInput'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input, NativeSelect } from '@/components/ui/input'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import type { CompanySize } from '@/lib/api'
import { applyApiErrors, focusFirstError } from '@/lib/forms'
import { paths } from '@/routes/paths'
import { useAuth } from '../hooks/useAuth'
import { employerSchema, type EmployerValues } from '../lib/schemas'

const FIELDS = [
  'first_name',
  'last_name',
  'email',
  'phone',
  'password',
  'confirm_password',
  'job_title',
  'company_name',
  'company_industry',
  'company_website',
  'company_location',
  'company_size',
] as const

const SIZES: CompanySize[] = ['1-10', '11-50', '51-200', '201-1000', '1000+']

const normalizeUrl = (v: string) => (v ? (/^https?:\/\//i.test(v) ? v : `https://${v}`) : null)

export default function RegisterEmployerPage() {
  useDocumentTitle('Register your company')
  const { registerEmployer } = useAuth()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    setError,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<EmployerValues>({
    resolver: zodResolver(employerSchema),
    defaultValues: {
      first_name: '',
      last_name: '',
      email: '',
      phone: '',
      password: '',
      confirm_password: '',
      job_title: '',
      company_name: '',
      company_industry: '',
      company_website: '',
      company_location: '',
      company_size: '',
    },
  })
  const password = watch('password')

  const onSubmit = handleSubmit(
    async (v) => {
      setFormError(null)
      try {
        const me = await registerEmployer({
          first_name: v.first_name,
          last_name: v.last_name,
          email: v.email,
          password: v.password,
          phone: v.phone || null,
          job_title: v.job_title || null,
          company_name: v.company_name,
          company_industry: v.company_industry || null,
          company_website: normalizeUrl(v.company_website),
          company_location: v.company_location || null,
          company_size: v.company_size || null,
        })
        toast.success(`${me.company?.name ?? 'Your company'} is ready. Let's post your first job.`)
        navigate(paths.manageJobs, { replace: true })
      } catch (e) {
        setFormError(
          applyApiErrors(e, setError, {
            fields: FIELDS,
            codeFields: { EMAIL_ALREADY_REGISTERED: 'email', COMPANY_NAME_TAKEN: 'company_name' },
          }),
        )
        focusFirstError()
      }
    },
    () => focusFirstError(),
  )

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Register your company</h1>
        <p className="text-sm text-muted-foreground">Create your recruiter account and company workspace in one step.</p>
      </div>
      {formError && <Alert variant="danger">{formError}</Alert>}
      <form onSubmit={onSubmit} noValidate className="grid gap-6" aria-label="Register as employer">
        <fieldset className="grid gap-4">
          <legend className="mb-1 text-sm font-semibold">Your account</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name" error={errors.first_name?.message} required>
              <Input autoComplete="given-name" {...register('first_name')} />
            </Field>
            <Field label="Last name" error={errors.last_name?.message} required>
              <Input autoComplete="family-name" {...register('last_name')} />
            </Field>
          </div>
          <Field label="Work email" error={errors.email?.message} required>
            <Input type="email" autoComplete="email" inputMode="email" placeholder="you@company.com" {...register('email')} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Job title" error={errors.job_title?.message} optional>
              <Input autoComplete="organization-title" placeholder="Head of Talent" {...register('job_title')} />
            </Field>
            <Field label="Phone" error={errors.phone?.message} optional>
              <Input type="tel" autoComplete="tel" {...register('phone')} />
            </Field>
          </div>
          <Field label="Password" error={errors.password?.message} required>
            <PasswordInput autoComplete="new-password" {...register('password')} />
          </Field>
          <PasswordRules value={password ?? ''} />
          <Field label="Confirm password" error={errors.confirm_password?.message} required>
            <PasswordInput autoComplete="new-password" {...register('confirm_password')} />
          </Field>
        </fieldset>

        <fieldset className="grid gap-4">
          <legend className="mb-1 text-sm font-semibold">Your company</legend>
          <Field label="Company name" error={errors.company_name?.message} required>
            <Input autoComplete="organization" {...register('company_name')} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Industry" error={errors.company_industry?.message} optional>
              <Input placeholder="Software" {...register('company_industry')} />
            </Field>
            <Field label="Company size" error={errors.company_size?.message} optional>
              <NativeSelect {...register('company_size')}>
                <option value="">Select size</option>
                {SIZES.map((s) => (
                  <option key={s} value={s}>
                    {s} employees
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <Field label="Website" error={errors.company_website?.message} optional>
            <Input type="url" inputMode="url" placeholder="https://example.com" {...register('company_website')} />
          </Field>
          <Field label="Headquarters" error={errors.company_location?.message} optional>
            <Input placeholder="Berlin, Germany" {...register('company_location')} />
          </Field>
        </fieldset>

        <Button type="submit" size="lg" loading={isSubmitting}>
          Create company account
        </Button>
      </form>
      <p className="text-center text-sm text-muted-foreground">
        Looking for work?{' '}
        <Link to={paths.register} className="font-medium text-primary hover:underline">
          Create a candidate account
        </Link>{' '}
        · Already registered?{' '}
        <Link to={paths.login} className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  )
}
