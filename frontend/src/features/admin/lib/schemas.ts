import { z } from 'zod'
import {
  emailSchema,
  nameSchema,
  optionalPhoneSchema,
  optionalUrlSchema,
  passwordSchema,
} from '@/features/auth/lib/schemas'
import { isStaffRole } from './labels'

/** Create-user form (POST /users). Mirrors backend `AdminUserCreate` + `UserService.create` rules. */
export const createUserSchema = z
  .object({
    first_name: nameSchema('first name'),
    last_name: nameSchema('last name'),
    email: emailSchema,
    phone: optionalPhoneSchema,
    role: z.enum(['ADMIN', 'RECRUITER', 'HIRING_MANAGER', 'CANDIDATE']),
    company_id: z.string(),
    password: passwordSchema,
  })
  .superRefine((v, ctx) => {
    if (isStaffRole(v.role) && !v.company_id)
      ctx.addIssue({
        code: 'custom',
        path: ['company_id'],
        message: 'Choose the company this recruiter or hiring manager belongs to',
      })
  })
export type CreateUserValues = z.infer<typeof createUserSchema>

export const COMPANY_SIZES = ['1-10', '11-50', '51-200', '201-1000', '1000+'] as const

/** Create-company form (POST /companies). */
export const createCompanySchema = z.object({
  name: z.string().trim().min(2, 'Company name must be at least 2 characters').max(200, 'Name is too long'),
  industry: z.string().trim().max(100, 'Industry is too long'),
  website: optionalUrlSchema,
  location: z.string().trim().max(200, 'Location is too long'),
  size: z.union([z.literal(''), z.enum(COMPANY_SIZES)]),
  description: z.string().trim().max(5000, 'Description is too long'),
})
export type CreateCompanyValues = z.infer<typeof createCompanySchema>

/** "example.com" -> "https://example.com"; empty stays empty. */
export const normalizeUrl = (v: string): string => {
  const t = v.trim()
  return !t || /^https?:\/\//i.test(t) ? t : `https://${t}`
}
