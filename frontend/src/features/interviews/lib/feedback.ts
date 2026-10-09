import { z } from 'zod'
import { RECOMMENDATIONS, type FeedbackIn, type FeedbackOut, type HireRecommendation } from '../api/types'

export interface FeedbackFormValues {
  /** '' until chosen, then '1'..'5' (radio values are strings) */
  rating: string
  /** '' until chosen */
  recommendation: string
  strengths: string
  weaknesses: string
  notes: string
}

const text = (label: string) => z.string().max(4000, `Keep ${label} under 4,000 characters`)

export const feedbackSchema = z.object({
  rating: z.string().regex(/^[1-5]$/, 'Choose a rating from 1 to 5'),
  recommendation: z
    .string()
    .refine((v) => (RECOMMENDATIONS as readonly string[]).includes(v), 'Choose a recommendation'),
  strengths: text('strengths'),
  weaknesses: text('weaknesses'),
  notes: text('notes'),
})

export const emptyFeedback: FeedbackFormValues = {
  rating: '',
  recommendation: '',
  strengths: '',
  weaknesses: '',
  notes: '',
}

export const feedbackToValues = (f: FeedbackOut): FeedbackFormValues => ({
  rating: String(f.rating),
  recommendation: f.recommendation,
  strengths: f.strengths ?? '',
  weaknesses: f.weaknesses ?? '',
  notes: f.notes ?? '',
})

export function toFeedbackPayload(v: FeedbackFormValues): FeedbackIn {
  return {
    rating: Number(v.rating),
    recommendation: v.recommendation as HireRecommendation,
    strengths: v.strengths.trim() || null,
    weaknesses: v.weaknesses.trim() || null,
    notes: v.notes.trim() || null,
  }
}
