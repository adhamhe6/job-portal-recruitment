import { zodResolver } from '@hookform/resolvers/zod'
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PasswordInput } from '@/components/common/PasswordInput'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { ApiError } from '@/lib/api'
import { ROLE_LABELS } from '@/lib/enums'
import { applyApiErrors } from '@/lib/forms'
import { safeRedirect } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { useDemoAccounts } from '../api/meta'
import { useAuth } from '../hooks/useAuth'
import { loginSchema, type LoginValues } from '../lib/schemas'

function loginErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'INVALID_CREDENTIALS') return 'Incorrect email or password. Please check them and try again.'
    if (e.code === 'ACCOUNT_SUSPENDED') return 'This account has been suspended. Contact your administrator.'
    if (e.status === 429 || e.code === 'RATE_LIMITED') return 'Too many sign-in attempts. Please wait a minute and try again.'
    return e.message
  }
  return 'Could not sign in. Please try again.'
}

export default function LoginPage() {
  useDocumentTitle('Sign in')
  const { login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeRedirect(params.get('next'), paths.dashboard)
  const demo = useDemoAccounts()
  const [formError, setFormError] = useState<string | null>(null)
  const [demoBusy, setDemoBusy] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: '', password: '' } })

  const signIn = async (email: string, password: string) => {
    setFormError(null)
    try {
      await login(email, password)
      navigate(next, { replace: true })
    } catch (e) {
      const mapped = e instanceof ApiError && e.code === 'VALIDATION_ERROR' ? applyApiErrors(e, setError, { fields: ['email', 'password'] }) : loginErrorMessage(e)
      setFormError(mapped)
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
        <p className="text-sm text-muted-foreground">Sign in to continue to TalentLens.</p>
      </div>

      {params.get('next') && !formError && (
        <Alert variant="info">Sign in to continue where you left off.</Alert>
      )}
      {formError && <Alert variant="danger">{formError}</Alert>}

      <form onSubmit={handleSubmit((v) => signIn(v.email, v.password))} noValidate className="grid gap-4" aria-label="Sign in">
        <Field label="Email" error={errors.email?.message} required>
          <Input type="email" autoComplete="username" inputMode="email" placeholder="you@company.com" {...register('email')} />
        </Field>
        <Field label="Password" error={errors.password?.message} required>
          <PasswordInput autoComplete="current-password" {...register('password')} />
        </Field>
        <Button type="submit" size="lg" loading={isSubmitting && !demoBusy} disabled={Boolean(demoBusy)}>
          Sign in
        </Button>
      </form>

      {demo && (
        <section aria-labelledby="demo-heading" className="space-y-3 rounded-xl border border-dashed bg-surface p-4">
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden />
            <h2 id="demo-heading" className="text-sm font-semibold">
              Try a demo account
            </h2>
            <Badge variant="muted" className="ml-auto">
              One click
            </Badge>
          </div>
          <ul className="grid gap-2">
            {demo.accounts.map((a) => (
              <li key={a.email}>
                <button
                  type="button"
                  disabled={isSubmitting || Boolean(demoBusy)}
                  onClick={async () => {
                    setDemoBusy(a.email)
                    await signIn(a.email, demo.password)
                    setDemoBusy(null)
                  }}
                  className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg border bg-card px-3 py-2.5 text-left text-sm transition-colors hover:border-primary/50 hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{a.label}</span>
                    <span className="block truncate text-xs text-muted-foreground">{a.email}</span>
                  </span>
                  <Badge variant="default">{demoBusy === a.email ? 'Signing in…' : (ROLE_LABELS[a.role as keyof typeof ROLE_LABELS] ?? a.role)}</Badge>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="space-y-2 text-center text-sm text-muted-foreground">
        <p>
          New to TalentLens?{' '}
          <Link to={paths.register} className="font-medium text-primary hover:underline">
            Create a candidate account
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
