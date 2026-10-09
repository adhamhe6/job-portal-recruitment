import { z } from 'zod'
import { emailSchema, nameSchema, optionalPhoneSchema, passwordSchema } from '@/features/auth/lib/schemas'

const SIZES = ['1-10', '11-50', '51-200', '201-1000', '1000+'] as const
export const SIZE_OPTIONS = SIZES.map((s) => ({ value: s, label: `${s} employees` }))

/** http(s) URL or empty. Bare domains ("example.com") are accepted and normalised on submit. */
const urlField = (message: string) =>
  z
    .string()
    .trim()
    .max(500, 'Address is too long')
    .refine((v) => {
      if (v === '') return true
      if (/\s/.test(v)) return false
      try {
        const u = new URL(/^https?:\/\//i.test(v) ? v : `https://${v}`)
        return u.hostname.includes('.')
      } catch {
        return false
      }
    }, message)

/** Company profile (PATCH /companies/{id}); mirrors backend `CompanyUpdate`. */
export const companyProfileSchema = z.object({
  name: z.string().trim().min(2, 'Company name must be at least 2 characters').max(200, 'Name is too long'),
  description: z.string().trim().max(5000, 'Keep the description under 5,000 characters'),
  website: urlField('Enter a valid website address, e.g. https://example.com'),
  industry: z.string().trim().max(100, 'Industry is too long'),
  size: z.union([z.literal(''), z.enum(SIZES)]),
  location: z.string().trim().max(200, 'Location is too long'),
  logo_url: urlField('Enter a valid image address, e.g. https://example.com/logo.png'),
})
export type CompanyProfileValues = z.infer<typeof companyProfileSchema>

export const normalizeUrl = (v: string): string => {
  const t = v.trim()
  return !t || /^https?:\/\//i.test(t) ? t : `https://${t}`
}

/** Empty strings clear optional fields (explicit null on PATCH). */
export function toCompanyPayload(v: CompanyProfileValues) {
  return {
    name: v.name.trim(),
    description: v.description.trim() || null,
    website: normalizeUrl(v.website) || null,
    industry: v.industry.trim() || null,
    size: v.size || null,
    location: v.location.trim() || null,
    logo_url: normalizeUrl(v.logo_url) || null,
  }
}

export const MEMBER_ROLES = ['RECRUITER', 'HIRING_MANAGER'] as const

export const addMemberSchema = z.object({
  first_name: nameSchema('first name'),
  last_name: nameSchema('last name'),
  email: emailSchema,
  phone: optionalPhoneSchema,
  role: z.enum(MEMBER_ROLES),
  job_title: z.string().trim().max(150, 'Job title is too long'),
  department: z.string().trim().max(100, 'Department is too long'),
  password: passwordSchema,
})
export type AddMemberValues = z.infer<typeof addMemberSchema>

export const editMemberSchema = z.object({
  role: z.enum(MEMBER_ROLES),
  job_title: z.string().trim().max(150, 'Job title is too long'),
  department: z.string().trim().max(100, 'Department is too long'),
})
export type EditMemberValues = z.infer<typeof editMemberSchema>
