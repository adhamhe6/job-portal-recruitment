import { z } from 'zod'

/** Client-side validation mirroring backend/app/schemas/auth.py (the server stays the source of truth). */

export const emailSchema = z.string().trim().min(1, 'Enter your email address').max(254).email('Enter a valid email address')

export const passwordSchema = z
  .string()
  .min(10, 'Use at least 10 characters')
  .max(128, 'Use at most 128 characters')
  .regex(/[A-Za-z]/, 'Include at least one letter')
  .regex(/\d/, 'Include at least one number')

const PHONE_RE = /^[+()\d][\d\s().-]{5,30}$/
export const optionalPhoneSchema = z
  .string()
  .trim()
  .max(32, 'Phone number is too long')
  .refine((v) => v === '' || PHONE_RE.test(v), 'Enter a valid phone number')

export const nameSchema = (label: string) =>
  z.string().trim().min(1, `Enter your ${label}`).max(100, `${label[0]?.toUpperCase()}${label.slice(1)} is too long`)

export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Enter your password'),
})
export type LoginValues = z.infer<typeof loginSchema>

const accountFields = {
  first_name: nameSchema('first name'),
  last_name: nameSchema('last name'),
  email: emailSchema,
  phone: optionalPhoneSchema,
  password: passwordSchema,
  confirm_password: z.string().min(1, 'Confirm your password'),
}

export const registerSchema = z.object(accountFields).refine((v) => v.password === v.confirm_password, {
  path: ['confirm_password'],
  message: 'Passwords do not match',
})
export type RegisterValues = z.infer<typeof registerSchema>

/** Accepts "example.com" and normalises on submit; rejects obviously invalid values. */
export const optionalUrlSchema = z
  .string()
  .trim()
  .max(500, 'Website address is too long')
  .refine((v) => {
    if (v === '') return true
    try {
      const u = new URL(/^https?:\/\//i.test(v) ? v : `https://${v}`)
      return u.hostname.includes('.')
    } catch {
      return false
    }
  }, 'Enter a valid website address, e.g. https://example.com')

export const employerSchema = z
  .object({
    ...accountFields,
    job_title: z.string().trim().max(150, 'Job title is too long'),
    company_name: z.string().trim().min(2, 'Company name must be at least 2 characters').max(200, 'Company name is too long'),
    company_industry: z.string().trim().max(100, 'Industry is too long'),
    company_website: optionalUrlSchema,
    company_location: z.string().trim().max(200, 'Location is too long'),
    company_size: z.enum(['', '1-10', '11-50', '51-200', '201-1000', '1000+']),
  })
  .refine((v) => v.password === v.confirm_password, { path: ['confirm_password'], message: 'Passwords do not match' })
export type EmployerValues = z.infer<typeof employerSchema>

export const profileSchema = z.object({
  first_name: nameSchema('first name'),
  last_name: nameSchema('last name'),
  phone: optionalPhoneSchema,
})
export type ProfileValues = z.infer<typeof profileSchema>

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password'),
    new_password: passwordSchema,
    confirm_password: z.string().min(1, 'Confirm your new password'),
  })
  .refine((v) => v.new_password === v.confirm_password, { path: ['confirm_password'], message: 'Passwords do not match' })
  .refine((v) => v.new_password !== v.current_password, { path: ['new_password'], message: 'Choose a password different from your current one' })
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>
