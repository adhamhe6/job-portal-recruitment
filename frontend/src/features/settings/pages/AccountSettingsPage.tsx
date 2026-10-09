import { zodResolver } from '@hookform/resolvers/zod'
import { Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { PasswordInput, PasswordRules } from '@/components/common/PasswordInput'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { authApi } from '@/features/auth/api/auth'
import { useAuth } from '@/features/auth/hooks/useAuth'
import {
  changePasswordSchema,
  profileSchema,
  type ChangePasswordValues,
  type ProfileValues,
} from '@/features/auth/lib/schemas'
import { ROLE_LABELS } from '@/lib/enums'
import { applyApiErrors } from '@/lib/forms'
import { useTheme, type ThemePreference } from '@/lib/theme'
import { paths } from '@/routes/paths'

function ProfileCard() {
  const { user, setUser } = useAuth()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      first_name: user?.first_name ?? '',
      last_name: user?.last_name ?? '',
      phone: user?.phone ?? '',
    },
  })
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = form

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null)
    try {
      const me = await authApi.updateMe({
        first_name: values.first_name,
        last_name: values.last_name,
        phone: values.phone || null,
      })
      setUser(me)
      reset({ first_name: me.first_name, last_name: me.last_name, phone: me.phone ?? '' })
      toast.success('Account details updated')
    } catch (e) {
      setFormError(applyApiErrors(e, setError, { fields: ['first_name', 'last_name', 'phone'] }))
    }
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account details</CardTitle>
        <CardDescription>
          Signed in as {user?.email} · {user ? ROLE_LABELS[user.role] : ''}
          {user?.company ? ` at ${user.company.name}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Account details">
          {formError && <Alert variant="danger">{formError}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="First name" error={errors.first_name?.message} required>
              <Input autoComplete="given-name" {...register('first_name')} />
            </Field>
            <Field label="Last name" error={errors.last_name?.message} required>
              <Input autoComplete="family-name" {...register('last_name')} />
            </Field>
          </div>
          <Field label="Email" hint="Your email is your sign-in name and can't be changed here.">
            <Input value={user?.email ?? ''} readOnly disabled />
          </Field>
          <Field label="Phone" error={errors.phone?.message} optional>
            <Input type="tel" autoComplete="tel" placeholder="+49 30 1234567" {...register('phone')} />
          </Field>
          <div className="flex justify-end">
            <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
              Save changes
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function PasswordCard() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
  })
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = form
  const newPassword = useWatch({ control, name: 'new_password' })

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null)
    try {
      await authApi.changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      // The backend revokes every session on a password change: sign out locally and ask for the new credentials.
      await logout()
      toast.success('Password updated. Please sign in with your new password.')
      navigate(paths.login, { replace: true })
    } catch (e) {
      const message = applyApiErrors(e, setError, {
        fields: ['current_password', 'new_password'],
        fieldMap: { current_password: 'current_password' },
        codeFields: {
          INVALID_CREDENTIALS: 'current_password',
          INVALID_PASSWORD: 'current_password',
          WRONG_PASSWORD: 'current_password',
        },
      })
      setFormError(message)
    }
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>
          For your security, changing your password signs you out of every device.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="grid gap-4" aria-label="Change password">
          {formError && <Alert variant="danger">{formError}</Alert>}
          <Field label="Current password" error={errors.current_password?.message} required>
            <PasswordInput autoComplete="current-password" {...register('current_password')} />
          </Field>
          <Field label="New password" error={errors.new_password?.message} required>
            <PasswordInput autoComplete="new-password" {...register('new_password')} />
          </Field>
          <PasswordRules value={newPassword ?? ''} />
          <Field label="Confirm new password" error={errors.confirm_password?.message} required>
            <PasswordInput autoComplete="new-password" {...register('confirm_password')} />
          </Field>
          <div className="flex justify-end">
            <Button type="submit" loading={isSubmitting}>
              Update password
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

const THEMES: { value: ThemePreference; label: string; hint: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'System', hint: 'Match your device', icon: Monitor },
  { value: 'light', label: 'Light', hint: 'Always light', icon: Sun },
  { value: 'dark', label: 'Dark', hint: 'Always dark', icon: Moon },
]

function AppearanceCard() {
  const { preference, setPreference } = useTheme()
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>Choose how TalentLens looks on this device.</CardDescription>
      </CardHeader>
      <CardContent>
        <RadioGroup
          value={preference}
          onValueChange={(v) => setPreference(v as ThemePreference)}
          aria-label="Theme"
          className="grid gap-3 sm:grid-cols-3"
        >
          {THEMES.map(({ value, label, hint, icon: Icon }) => (
            <label
              key={value}
              htmlFor={`theme-${value}`}
              className="flex cursor-pointer items-center gap-3 rounded-xl border bg-card p-3.5 transition-colors hover:bg-accent/50 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary-soft/50 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring"
            >
              <RadioGroupItem value={value} id={`theme-${value}`} />
              <Icon className="size-5 text-muted-foreground" aria-hidden />
              <span>
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-xs text-muted-foreground">{hint}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
      </CardContent>
    </Card>
  )
}

export default function AccountSettingsPage() {
  return (
    <div className="grid gap-6">
      <ProfileCard />
      <AppearanceCard />
      <PasswordCard />
    </div>
  )
}
