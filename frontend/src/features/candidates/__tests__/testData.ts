import type { CandidateListItem, CandidateView } from '../api/candidates'
import type { MatchDetail, MatchedCandidate, RankedCandidatesMeta } from '@/features/matches/api/matches'

export const JOB_ID = 'job-live-1'

export function makeCandidateItem(overrides: Partial<CandidateListItem> = {}): CandidateListItem {
  return {
    id: 'cand-1',
    display_name: 'Priya Nair',
    headline: 'Data Scientist, Experimentation and NLP',
    location: 'Berlin, Germany',
    years_experience: '3.0',
    availability: 'TWO_WEEKS',
    remote_preference: 'HYBRID',
    source: 'SELF',
    access: 'FULL',
    top_skills: ['Python', 'SQL', 'Statistics'],
    skill_matches: [],
    match_score: null,
    match_band: null,
    has_applied: false,
    updated_at: '2026-10-01T10:00:00Z',
    ...overrides,
  }
}

export function makeCandidateView(overrides: Partial<CandidateView> = {}): CandidateView {
  return {
    id: 'cand-1',
    display_name: 'Priya Nair',
    source: 'SELF',
    access: 'FULL',
    headline: 'Data Scientist, Experimentation and NLP',
    summary: 'Statistician who builds NLP classifiers.',
    location: 'Berlin, Germany',
    years_experience: '3.0',
    expected_salary: '78000.00',
    salary_currency: 'EUR',
    remote_preference: 'HYBRID',
    employment_preference: 'FULL_TIME',
    availability: 'TWO_WEEKS',
    portfolio_url: null,
    linkedin_url: null,
    github_url: 'https://github.com/priya-nair',
    email: 'priya.nair@demo.example',
    phone: '+49 30 1234567',
    skills: [
      {
        id: 'cs-1',
        skill: { id: 's-py', name: 'Python', category: 'Languages', family: null, is_verified: true },
        proficiency: 'ADVANCED',
        years_experience: '4.0',
        source: 'USER',
        status: 'CONFIRMED',
        confidence: null,
      },
      {
        id: 'cs-2',
        skill: { id: 's-rs', name: 'Rust', category: 'Languages', family: null, is_verified: true },
        proficiency: null,
        years_experience: null,
        source: 'RESUME',
        status: 'SUGGESTED',
        confidence: 0.6,
      },
    ],
    experiences: [
      {
        id: 'ex-1',
        title: 'Data Scientist',
        company_name: 'Clickstream',
        location: null,
        start_date: '2023-10-10',
        end_date: null,
        is_current: true,
        description: 'Built text classifiers.',
        source: 'USER',
      },
    ],
    educations: [
      {
        id: 'ed-1',
        institution: 'University of Edinburgh',
        degree_level: 'MASTER',
        degree: 'MSc Statistics',
        field_of_study: 'Statistics',
        start_year: 2016,
        end_year: 2018,
        source: 'USER',
      },
    ],
    certifications: [],
    languages: [{ id: 'l-1', language: 'English', proficiency: 'FLUENT' }],
    resumes: [
      {
        id: 'res-1',
        status: 'PROCESSED',
        is_primary: true,
        original_filename: 'priya-nair.pdf',
        created_at: '2026-09-20T10:00:00Z',
      },
    ],
    applications: [
      {
        id: 'app-9',
        job_id: JOB_ID,
        job_title: 'Machine Learning Engineer',
        status: 'SCREENING',
        applied_at: '2026-10-03T11:13:57Z',
      },
    ],
    updated_at: '2026-10-01T10:00:00Z',
    match: null,
    ...overrides,
  }
}

export function makeMatched(overrides: Partial<MatchedCandidate> = {}): MatchedCandidate {
  return {
    candidate_id: 'cand-1',
    display_name: 'Priya Nair',
    headline: 'Data Scientist, Experimentation and NLP',
    location: 'Berlin, Germany',
    years_experience: '3.0',
    availability: 'TWO_WEEKS',
    overall_score: 0.7905,
    overall_percent: 79,
    band: 'STRONG',
    breakdown: {
      semantic: 0.66,
      required_skills: 0.75,
      preferred_skills: null,
      experience: 1,
      education: 1,
      preferences: 1,
    },
    summary: 'Strong match; covers 3 of 4 required skills.',
    strong_skills: ['Python', 'Machine Learning'],
    related_skills: [{ required: 'PyTorch', candidate_has: 'TensorFlow' }],
    missing_required: ['Kubernetes'],
    missing_preferred: ['MLOps'],
    experience_text: '3 years vs 3+ years required',
    semantic_band: 'MEDIUM',
    has_applied: true,
    application_id: 'app-9',
    application_status: 'SCREENING',
    access: 'FULL',
    stale: false,
    generated_at: new Date(Date.now() - 3_600_000).toISOString(),
    ...overrides,
  }
}

export function makeMeta(overrides: Partial<RankedCandidatesMeta> = {}): RankedCandidatesMeta {
  return {
    job_id: JOB_ID,
    total_scored: 16,
    last_generated_at: new Date(Date.now() - 3_600_000).toISOString(),
    stale_rows: 0,
    embedding_model: 'wordllama-l2-supercat-256',
    matching_version: 'v1',
    computing_task_id: null,
    ...overrides,
  }
}

export function makeMatchDetail(overrides: Partial<MatchDetail> = {}): MatchDetail {
  return {
    job_id: JOB_ID,
    job_title: 'Machine Learning Engineer',
    candidate_id: 'cand-1',
    candidate_name: 'Priya Nair',
    overall_score: 0.7905,
    overall_percent: 79,
    band: 'STRONG',
    breakdown: {
      semantic: 0.6629,
      required_skills: 0.75,
      preferred_skills: 0.6667,
      experience: 1,
      education: 1,
      preferences: 1,
    },
    explanation: {
      band: 'STRONG',
      skills: {
        required: {
          total: 4,
          matched: [
            { name: 'Machine Learning', source: 'USER' },
            { name: 'Python', source: 'USER' },
          ],
          missing: ['PyTorch'],
          related: [],
          coverage: 0.75,
        },
        preferred: {
          total: 3,
          matched: [{ name: 'SQL', source: 'USER' }],
          missing: ['MLOps'],
          related: [],
          coverage: 0.6667,
        },
      },
      summary: 'Strong match; covers 3 of 4 required skills.',
      weights: {
        required: 0.3,
        semantic: 0.3,
        education: 0.05,
        preferred: 0.1,
        experience: 0.15,
        preference: 0.1,
      },
      semantic: { band: 'MEDIUM', score: 0.6629, cosine: 0.61 },
      education: { status: 'MEETS', required_level: 'MASTER', candidate_level: 'MASTER' },
      experience: {
        text: '3 years vs 3+ years required',
        status: 'MEETS',
        required_min: 3,
        candidate_years: 3,
      },
      preferences: { location: 'Same city', workplace: 'Job is hybrid; candidate prefers hybrid' },
      qualification_floor_applied: false,
    },
    embedding_model: 'wordllama-l2-supercat-256',
    embedding_version: 'v1',
    matching_version: 'v1',
    generated_at: new Date(Date.now() - 3_600_000).toISOString(),
    ...overrides,
  }
}
