import type { ApplicationListItem, JobListItem, Paginated } from '@/lib/api'
import type { components } from '@/lib/api'
import type { CandidateInterview } from '@/features/interviews/api/myInterviews'
import type { ExtractedResume, ResumeOut } from '@/features/resumes/api/resumes'
import type { CandidateProfile } from '@/features/profile/lib/types'
import { COMPANY_ID, makeJobListItem, skill, uid } from './fixtures'

/** Typed factories for the candidate-facing pages (profile, résumés, applications, interviews, recommendations). */

type S = components['schemas']

export function makeCompletion(over: Partial<S['ProfileCompletion']> = {}): S['ProfileCompletion'] {
  return {
    percent: 70,
    items: [
      { key: 'headline', label: 'Add a professional headline', weight: 10, done: true },
      { key: 'skills', label: 'Add at least 3 skills', weight: 20, done: true },
      { key: 'resume', label: 'Upload your résumé', weight: 15, done: false },
    ],
    missing: ['Upload your résumé'],
    ...over,
  }
}

export function makeProfile(over: Partial<CandidateProfile> = {}): CandidateProfile {
  return {
    id: 'cand-1',
    first_name: 'Alex',
    last_name: 'Rivera',
    email: 'candidate@demo.example',
    phone: null,
    headline: 'Backend engineer',
    summary: 'Ten years of building services.',
    location: 'Berlin, Germany',
    years_experience: '5.5',
    expected_salary: null,
    salary_currency: 'EUR',
    remote_preference: 'HYBRID',
    employment_preference: 'FULL_TIME',
    availability: 'TWO_WEEKS',
    portfolio_url: null,
    linkedin_url: null,
    github_url: null,
    is_searchable: true,
    skills: [
      {
        id: 'cs-1',
        skill: skill('Python'),
        proficiency: 'EXPERT',
        years_experience: '6.0',
        source: 'USER',
        status: 'CONFIRMED',
        confidence: null,
      },
    ],
    experiences: [
      {
        id: 'exp-1',
        title: 'Senior Engineer',
        company_name: 'Acme',
        location: 'Remote',
        start_date: '2021-01-01',
        end_date: null,
        is_current: true,
        description: null,
        source: 'USER',
      },
    ],
    educations: [
      {
        id: 'edu-1',
        institution: 'TU Berlin',
        degree_level: 'BACHELOR',
        degree: 'B.Sc.',
        field_of_study: 'Computer Science',
        start_year: 2012,
        end_year: 2016,
        source: 'USER',
      },
    ],
    certifications: [],
    languages: [{ id: 'lang-1', language: 'English', proficiency: 'FLUENT' }],
    completion: makeCompletion(),
    primary_resume: null,
    updated_at: '2026-10-08T10:00:00Z',
    ...over,
  }
}

export function makeResume(over: Partial<ResumeOut> = {}): ResumeOut {
  return {
    id: uid('res'),
    candidate_id: 'cand-1',
    status: 'PROCESSED',
    is_primary: true,
    original_filename: 'alex-cv.pdf',
    content_type: 'application/pdf',
    size_bytes: 48_211,
    sha256: 'abc',
    created_at: '2026-10-07T12:00:00Z',
    updated_at: '2026-10-07T12:00:04Z',
    task_id: 'task-1',
    processing: { task_id: 'task-1', task_status: 'COMPLETED', progress: 100, page_count: 2 },
    ...over,
  }
}

export function makeExtracted(over: Partial<ExtractedResume> = {}): ExtractedResume {
  return {
    resume_id: 'res-1',
    candidate_id: 'cand-1',
    parser_version: 'v1',
    has_corrections: false,
    contact: {
      name: 'Alex Rivera',
      email: 'alex@example.com',
      phone: '+49 151 2345 6789',
      location: 'Hamburg',
    },
    headline: 'Staff Backend Engineer',
    summary: null,
    years_of_experience: 7,
    years_basis: 'employment_history',
    skills: [
      {
        index: 0,
        name: 'Kubernetes',
        skill_id: 'sk-k8s',
        confidence: 0.92,
        listed: true,
        already_on_profile: false,
        status: 'SUGGESTED',
        corrected: false,
      },
      {
        index: 1,
        name: 'Python',
        skill_id: 'sk-py',
        confidence: 0.95,
        listed: true,
        already_on_profile: true,
        status: 'CONFIRMED',
        corrected: false,
      },
      {
        index: 2,
        name: 'Fortran77',
        skill_id: null,
        confidence: 0.4,
        listed: false,
        already_on_profile: false,
        status: null,
        corrected: false,
      },
    ],
    experiences: [
      {
        index: 0,
        title: 'Platform Engineer',
        company: 'Globex',
        location: null,
        start_date: '2018-03-01',
        end_date: '2020-12-01',
        is_current: false,
        description: null,
        confidence: 0.88,
        already_on_profile: false,
        corrected: false,
        missing_for_apply: [],
      },
      {
        index: 1,
        title: 'Developer',
        company: null,
        location: null,
        start_date: null,
        end_date: null,
        is_current: false,
        description: null,
        confidence: 0.45,
        already_on_profile: false,
        corrected: false,
        missing_for_apply: ['company', 'start_date'],
      },
    ],
    educations: [],
    certifications: [],
    languages: [],
    sections_detected: ['skills', 'experience'],
    warnings: [],
    ...over,
  }
}

export function makeMyApplication(over: Partial<ApplicationListItem> = {}): ApplicationListItem {
  return {
    id: uid('app'),
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    company_id: COMPANY_ID,
    company_name: 'Northwind Labs',
    candidate_id: 'cand-1',
    candidate_name: 'Alex Rivera',
    candidate_headline: null,
    status: 'APPLIED',
    applied_at: '2026-10-01T10:00:00Z',
    status_changed_at: '2026-10-02T10:00:00Z',
    match_score: null,
    match_band: null,
    has_resume: true,
    next_interview_at: null,
    ...over,
  }
}

export function makeInterview(over: Partial<CandidateInterview> = {}): CandidateInterview {
  return {
    audience: 'candidate',
    id: uid('int'),
    application_id: 'app-1',
    job_id: 'job-1',
    job_title: 'Senior Backend Engineer',
    company_name: 'Northwind Labs',
    interview_type: 'TECHNICAL',
    start_at: '2030-05-20T09:00:00Z',
    end_at: '2030-05-20T10:00:00Z',
    start_local: '2030-05-20T11:00:00+02:00',
    end_local: '2030-05-20T12:00:00+02:00',
    timezone: 'Europe/Berlin',
    duration_minutes: 60,
    location: null,
    meeting_url: 'https://meet.example.com/abc',
    status: 'SCHEDULED',
    interviewers: ['Riley Recruiter'],
    can_confirm: true,
    ...over,
  }
}

export function makeRecommendation(
  job: Partial<JobListItem> = {},
  match: Partial<S['CandidateFacingMatch']> = {},
): S['RecommendedJob'] {
  return {
    job: makeJobListItem(job),
    match: {
      overall_percent: 82,
      band: 'STRONG',
      summary: 'Strong match; covers 3 of 4 required skills.',
      matched_skills: ['Python', 'PostgreSQL'],
      related_skills: [{ required: 'Kafka', candidate_has: 'RabbitMQ' }],
      missing_required: ['Kubernetes'],
      missing_preferred: ['Terraform'],
      experience_text: '5.5 years vs 4+ years required',
      experience_status: 'MEETS',
      semantic_band: 'HIGH',
      generated_at: '2026-10-09T10:00:00Z',
      ...match,
    },
  }
}

export function recommendationsPage(
  items: S['RecommendedJob'][],
  meta: Partial<S['RecommendationsMeta']> = {},
): S['RecommendationsPage'] {
  return {
    items,
    page: 1,
    page_size: 10,
    total: items.length,
    pages: items.length ? 1 : 0,
    meta: {
      last_generated_at: '2026-10-09T10:00:00Z',
      computing: false,
      task_id: null,
      profile_ready: true,
      hint: null,
      ...meta,
    },
  }
}

export type { Paginated }
