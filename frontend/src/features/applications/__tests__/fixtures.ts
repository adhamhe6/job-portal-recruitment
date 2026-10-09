import type { ApplicationDetail, ApplicationListItem } from '@/lib/api'
import { COMPANY_ID, uid } from '@/test/fixtures'
import type { ApplicationNote } from '../api/applications'

export function makeApplicationItem(o: Partial<ApplicationListItem> = {}): ApplicationListItem {
  return {
    id: uid('app'),
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    company_id: COMPANY_ID,
    company_name: 'Northwind Labs',
    candidate_id: uid('cand'),
    candidate_name: 'Dana Candidate',
    candidate_headline: 'Backend engineer',
    status: 'APPLIED',
    applied_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
    status_changed_at: new Date(Date.now() - 86_400_000).toISOString(),
    match_score: 0.82,
    match_band: 'STRONG',
    has_resume: true,
    next_interview_at: null,
    ...o,
  }
}

export function makeApplicationDetail(o: Partial<ApplicationDetail> = {}): ApplicationDetail {
  return {
    id: 'app-1',
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    company_id: COMPANY_ID,
    company_name: 'Northwind Labs',
    candidate_id: 'cand-9',
    candidate_name: 'Dana Candidate',
    status: 'SCREENING',
    cover_letter: 'I love distributed systems.\n\nLet me tell you why.',
    resume_id: 'res-1',
    resume_filename: 'dana.pdf',
    source: 'DIRECT',
    rejection_reason: null,
    applied_at: '2026-10-01T10:00:00Z',
    status_changed_at: '2026-10-03T10:00:00Z',
    allowed_next_statuses: ['REJECTED', 'SHORTLISTED'],
    match: { overall_score: 0.82, band: 'STRONG', summary: 'Strong match; covers 4 of 5 required skills.' },
    history: [
      {
        id: 'h1',
        from_status: null,
        to_status: 'APPLIED',
        actor_name: 'Dana Candidate',
        comment: null,
        created_at: '2026-10-01T10:00:00Z',
      },
      {
        id: 'h2',
        from_status: 'APPLIED',
        to_status: 'SCREENING',
        actor_name: 'Riley Recruiter',
        comment: 'Looks promising',
        created_at: '2026-10-03T10:00:00Z',
      },
    ],
    ...o,
  }
}

export const makeNote = (o: Partial<ApplicationNote> = {}): ApplicationNote => ({
  id: uid('note'),
  author_id: 'user-recruiter',
  author_name: 'Riley Recruiter',
  body: 'Strong phone screen.',
  created_at: new Date(Date.now() - 3_600_000).toISOString(),
  ...o,
})

export const MATCH_DETAIL = {
  job_id: 'job-1',
  job_title: 'Senior Backend Engineer',
  candidate_id: 'cand-9',
  candidate_name: 'Dana Candidate',
  overall_score: 0.82,
  overall_percent: 82,
  band: 'STRONG',
  breakdown: {},
  explanation: {
    summary: 'Strong match; covers 4 of 5 required skills.',
    skills: {
      required: {
        total: 5,
        matched: [
          { name: 'Python', source: 'USER' },
          { name: 'PostgreSQL', source: 'USER' },
        ],
        missing: ['Kafka'],
        related: [{ required: 'Redis', candidate_has: 'Memcached' }],
        coverage: 0.8,
      },
      preferred: { total: 1, matched: [], missing: ['Terraform'], related: [], coverage: 0 },
    },
    experience: { text: '6 years vs 4+ years required', status: 'MEETS' },
  },
  embedding_model: 'x',
  embedding_version: '1',
  matching_version: '1',
  generated_at: new Date().toISOString(),
}
