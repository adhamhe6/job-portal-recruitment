import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import {
  buildJobSchema,
  EMPTY_JOB_FORM,
  formValuesToPayload,
  jobToFormValues,
  publishProblems,
  type JobFormValues,
} from '../lib/jobForm'
import { errorBody, makeJobDetail } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

const LONG_DESCRIPTION =
  'Own the services that power our developer products end to end, from design to on-call.'

type User = ReturnType<typeof renderApp>['user']
const field = (label: RegExp | string) => screen.getByLabelText(label)

async function paste(user: User, el: HTMLElement, text: string) {
  await user.click(el)
  await user.paste(text)
}

async function addSkill(user: User, name: string, { create = false }: { create?: boolean } = {}) {
  await user.click(screen.getByRole('combobox', { name: 'Skills' }))
  await user.type(await screen.findByPlaceholderText('Type a skill name…'), name)
  await user.click(
    await screen.findByRole('option', {
      name: create ? new RegExp(`Add “${name}” as a new skill`) : new RegExp(name),
    }),
  )
  await user.keyboard('{Escape}')
}

const capture = () => {
  const state: { body?: Record<string, unknown>; query?: URLSearchParams; publishCalls: number } = {
    publishCalls: 0,
  }
  server.use(
    http.post('/api/v1/jobs', async ({ request }) => {
      state.body = (await request.json()) as Record<string, unknown>
      state.query = new URL(request.url).searchParams
      return HttpResponse.json(
        makeJobDetail({ id: 'job-new', status: 'DRAFT', title: String(state.body.title) }),
        { status: 201 },
      )
    }),
    http.get('/api/v1/jobs/job-new', () =>
      HttpResponse.json(
        makeJobDetail({
          id: 'job-new',
          status: 'DRAFT',
          title: 'Platform Engineer',
          allowed_transitions: ['ARCHIVED', 'PUBLISHED'],
        }),
      ),
    ),
    http.get('/api/v1/jobs/job-new/stats', () =>
      HttpResponse.json({
        job_id: 'job-new',
        applications_total: 0,
        applications_by_status: {},
        matches_computed: 0,
        last_matched_at: null,
        extra: {},
      }),
    ),
    http.get('/api/v1/companies/:id/members', () =>
      HttpResponse.json([
        {
          id: 'u-hm',
          email: 'hm@x.example',
          first_name: 'Hannah',
          last_name: 'Manager',
          role: 'HIRING_MANAGER',
          status: 'ACTIVE',
          job_title: null,
          department: null,
          is_company_admin: false,
          last_login_at: null,
        },
      ]),
    ),
  )
  return state
}

describe('job form: schema and payload (unit)', () => {
  const schema = buildJobSchema()
  const valid: JobFormValues = {
    ...EMPTY_JOB_FORM,
    title: 'Platform Engineer',
    description: LONG_DESCRIPTION,
  }

  it('accepts a minimal valid job', () => {
    expect(schema.safeParse(valid).success).toBe(true)
  })

  it.each([
    ['title shorter than 3', { title: 'ab' }, 'title'],
    ['description shorter than 10', { description: 'too short' }, 'description'],
    ['salary max below min', { salary_min: '90000', salary_max: '80000' }, 'salary_max'],
    [
      'experience max below min',
      { min_experience_years: '5', max_experience_years: '3' },
      'max_experience_years',
    ],
    ['deadline in the past', { application_deadline: '2020-01-01' }, 'application_deadline'],
    ['negative salary', { salary_min: '-5' }, 'salary_min'],
    ['too many decimals', { salary_min: '10.123' }, 'salary_min'],
    ['bad currency code', { salary_currency: 'EURO' }, 'salary_currency'],
    [
      'skill years above 30',
      { skills: [{ name: 'Python', requirement: 'REQUIRED' as const, min_years: '31' }] },
      'skills',
    ],
  ])('rejects %s', (_label, patch, path) => {
    const res = schema.safeParse({ ...valid, ...patch })
    expect(res.success).toBe(false)
    expect(res.error?.issues.some((i) => i.path[0] === path)).toBe(true)
  })

  it('does not re-validate an unchanged (already past) deadline when editing', () => {
    const editSchema = buildJobSchema({ originalDeadline: '2020-01-01' })
    expect(editSchema.safeParse({ ...valid, application_deadline: '2020-01-01' }).success).toBe(true)
    expect(editSchema.safeParse({ ...valid, application_deadline: '2020-02-02' }).success).toBe(false)
  })

  it('rejects the same skill twice', () => {
    const dup = { name: 'Python', skill_id: 's1', requirement: 'REQUIRED' as const, min_years: '' }
    expect(
      schema.safeParse({ ...valid, skills: [dup, { ...dup, requirement: 'PREFERRED' as const }] }).success,
    ).toBe(false)
  })

  it('publish needs a 30+ character description and one required skill', () => {
    expect(publishProblems({ ...valid, description: 'Short but valid.' }).map((p) => p.field)).toEqual([
      'description',
      'skills',
    ])
    expect(
      publishProblems({ ...valid, skills: [{ name: 'Go', requirement: 'PREFERRED', min_years: '' }] }).map(
        (p) => p.field,
      ),
    ).toEqual(['skills'])
    expect(
      publishProblems({ ...valid, skills: [{ name: 'Go', requirement: 'REQUIRED', min_years: '' }] }),
    ).toEqual([])
  })

  it('maps form values to the API payload (explicit nulls for cleared fields; skills by id or by name)', () => {
    const payload = formValuesToPayload({
      ...valid,
      department: '  ',
      salary_min: '70000',
      salary_currency: 'eur',
      hiring_manager_id: '',
      skills: [
        { skill_id: 'abc', name: 'Python', requirement: 'REQUIRED', min_years: '3' },
        { name: 'Rust', requirement: 'PREFERRED', min_years: '' },
      ],
    })
    expect(payload).toMatchObject({
      title: 'Platform Engineer',
      department: null,
      salary_min: 70000,
      salary_max: null,
      salary_currency: 'EUR',
      experience_level: null,
      hiring_manager_id: null,
      min_experience_years: 0,
      skills: [
        { skill_id: 'abc', requirement: 'REQUIRED', min_years: 3 },
        { name: 'Rust', requirement: 'PREFERRED', min_years: null },
      ],
    })
  })

  it('round-trips an API job into form values', () => {
    const values = jobToFormValues(
      makeJobDetail({ salary_min: '90000.00', min_experience_years: '4.0', max_experience_years: null }),
    )
    expect(values).toMatchObject({
      salary_min: '90000',
      min_experience_years: '4',
      max_experience_years: '',
      hiring_manager_id: '',
    })
    expect(values.skills[1]).toMatchObject({ name: 'PostgreSQL', min_years: '3', requirement: 'REQUIRED' })
  })
})

describe('create job', () => {
  it('validates on the client and does not call the API', async () => {
    signInAs('RECRUITER')
    let posted = false
    server.use(http.post('/api/v1/jobs', () => ((posted = true), HttpResponse.json({}))))
    const { user } = renderApp('/manage/jobs/new')
    await user.click(await screen.findByRole('button', { name: /save as draft/i }))
    expect(await screen.findByText('Title must be at least 3 characters')).toBeInTheDocument()
    expect(screen.getByText('Description must be at least 10 characters')).toBeInTheDocument()
    expect(field(/job title/i)).toHaveAttribute('aria-invalid', 'true')
    expect(
      screen.getByText('Some fields need your attention. They are highlighted below.'),
    ).toBeInTheDocument()
    expect(posted).toBe(false)
  })

  it('checks salary and experience ranges', async () => {
    signInAs('RECRUITER')
    const { user } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await user.type(field(/salary from/i), '90000')
    await user.type(field(/salary up to/i), '80000')
    await user.clear(field(/min\. experience/i))
    await user.type(field(/min\. experience/i), '5')
    await user.type(field(/max\. experience/i), '3')
    await user.click(screen.getByRole('button', { name: /save as draft/i }))
    expect(await screen.findByText('Maximum salary must be at least the minimum')).toBeInTheDocument()
    expect(screen.getByText('Maximum experience must be at least the minimum')).toBeInTheDocument()
  })

  it('publishing without a required skill is stopped before the request, with a clear list', async () => {
    signInAs('RECRUITER')
    let posted = false
    server.use(http.post('/api/v1/jobs', () => ((posted = true), HttpResponse.json({}))))
    const { user } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), 'Short description.')
    await user.click(screen.getByRole('button', { name: 'Publish' }))
    const alert = await screen.findByText('This job can’t be published yet')
    const box = alert.closest('div[role="status"]') as HTMLElement
    expect(within(box).getByText('Description must be at least 30 characters to publish')).toBeInTheDocument()
    expect(within(box).getByText('Add at least one required skill to publish')).toBeInTheDocument()
    expect(posted).toBe(false)
  })

  it('saves a draft: skills (existing and newly typed) go in the payload, then continues on the edit page', async () => {
    signInAs('RECRUITER')
    const sent = capture()
    const { user, router } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await addSkill(user, 'Python')
    await addSkill(user, 'Rust', { create: true })
    expect(screen.getByText('New skill')).toBeInTheDocument()
    // mark Rust as preferred and give Python a minimum
    await user.click(
      within(screen.getByRole('radiogroup', { name: 'Requirement level for Rust' })).getByRole('radio', {
        name: 'Preferred',
      }),
    )
    await user.type(screen.getByLabelText('Minimum years of Python'), '3')
    await user.click(screen.getByRole('button', { name: /save as draft/i }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/manage/jobs/job-new/edit'))
    expect(sent.body).toMatchObject({
      title: 'Platform Engineer',
      description: LONG_DESCRIPTION,
      employment_type: 'FULL_TIME',
      workplace_type: 'ONSITE',
      salary_currency: 'USD',
      min_experience_years: 0,
      skills: [
        { skill_id: 'skill-python', requirement: 'REQUIRED', min_years: 3 },
        { name: 'Rust', requirement: 'PREFERRED', min_years: null },
      ],
    })
    expect(await screen.findByRole('heading', { name: /Edit “Platform Engineer”/ })).toBeInTheDocument()
    expect(await screen.findByText('Draft saved')).toBeInTheDocument()
  })

  it('publish = create the job, then POST /publish, then show the live job', async () => {
    signInAs('RECRUITER')
    const sent = capture()
    server.use(
      http.post('/api/v1/jobs/job-new/publish', () => {
        sent.publishCalls++
        return HttpResponse.json(
          makeJobDetail({ id: 'job-new', status: 'PUBLISHED', title: 'Platform Engineer' }),
        )
      }),
    )
    const { user, router } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await addSkill(user, 'Python')
    await user.click(screen.getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/jobs/job-new'))
    expect(sent.publishCalls).toBe(1)
    expect(await screen.findByText('Job published')).toBeInTheDocument()
  })

  it('shows the hiring manager options from the company members and sends the chosen id', async () => {
    signInAs('RECRUITER')
    const sent = capture()
    const { user } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await screen.findByRole('option', { name: /Hannah Manager — Hiring manager/ })
    await user.selectOptions(field(/hiring manager/i), 'u-hm')
    await user.click(screen.getByRole('button', { name: /save as draft/i }))
    await waitFor(() => expect(sent.body?.hiring_manager_id).toBe('u-hm'))
  })

  it('maps server field errors (422 details[]) back onto the fields', async () => {
    signInAs('RECRUITER')
    server.use(
      http.post('/api/v1/jobs', () =>
        HttpResponse.json(
          errorBody('VALIDATION_ERROR', 'Request validation failed', [
            { field: 'title', message: 'String should have at most 200 characters', type: 'string_too_long' },
            {
              field: 'application_deadline',
              message: 'Value error, application_deadline cannot be in the past',
              type: 'value_error',
            },
            {
              field: '',
              message: 'Value error, salary_max must be greater than or equal to salary_min',
              type: 'value_error',
            },
          ]),
          { status: 422 },
        ),
      ),
    )
    const { user } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await user.click(screen.getByRole('button', { name: /save as draft/i }))
    expect(await screen.findByText('String should have at most 200 characters')).toBeInTheDocument()
    expect(screen.getByText('application_deadline cannot be in the past')).toBeInTheDocument()
    expect(screen.getByText('salary_max must be greater than or equal to salary_min')).toBeInTheDocument()
    expect(field(/job title/i)).toHaveAttribute('aria-invalid', 'true')
  })

  it('explains DUPLICATE_JOB on the title field', async () => {
    signInAs('RECRUITER')
    server.use(
      http.post('/api/v1/jobs', () =>
        HttpResponse.json(
          errorBody(
            'DUPLICATE_JOB',
            'A live job with the same title, location and workplace type already exists',
          ),
          { status: 409 },
        ),
      ),
    )
    const { user } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await user.click(screen.getByRole('button', { name: /save as draft/i }))
    expect(
      await screen.findByText(/same title, location and workplace type already exists/),
    ).toBeInTheDocument()
    expect(field(/job title/i)).toHaveAttribute('aria-invalid', 'true')
  })

  it('PUBLISH_VALIDATION_FAILED from the server keeps the saved draft and lists what is missing', async () => {
    signInAs('RECRUITER')
    capture()
    server.use(
      http.post('/api/v1/jobs/job-new/publish', () =>
        HttpResponse.json(
          errorBody('PUBLISH_VALIDATION_FAILED', 'This job cannot be published yet', [
            'The company account is suspended',
          ]),
          { status: 422 },
        ),
      ),
    )
    const { user, router } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Platform Engineer')
    await paste(user, field(/about the role/i), LONG_DESCRIPTION)
    await addSkill(user, 'Python')
    await user.click(screen.getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/manage/jobs/job-new/edit'))
    expect(await screen.findByText('The company account is suspended')).toBeInTheDocument()
    expect(screen.getByText('This job can’t be published yet')).toBeInTheDocument()
  })

  it('guards against losing unsaved changes when leaving', async () => {
    signInAs('RECRUITER')
    const { user, router } = renderApp('/manage/jobs/new')
    await paste(user, await screen.findByLabelText(/job title/i), 'Half-written job')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Leave without saving?' })
    await user.click(within(dialog).getByRole('button', { name: 'Keep editing' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(router.state.location.pathname).toBe('/manage/jobs/new')
    expect(field(/job title/i)).toHaveValue('Half-written job')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Discard changes' }),
    )
    await waitFor(() => expect(router.state.location.pathname).toBe('/manage/jobs'))
  })

  it('does not nag when nothing was changed', async () => {
    signInAs('RECRUITER')
    const { user, router } = renderApp('/manage/jobs/new')
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/manage/jobs'))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})

describe('edit job', () => {
  it('prefills the form, warns that matches will refresh and PATCHes the changes', async () => {
    signInAs('RECRUITER')
    let patch: Record<string, unknown> = {}
    server.use(
      http.get('/api/v1/jobs/job-1', () =>
        HttpResponse.json(
          makeJobDetail({
            id: 'job-1',
            status: 'PUBLISHED',
            title: 'Senior Backend Engineer',
            department: 'Platform',
          }),
        ),
      ),
      http.get('/api/v1/jobs/job-1/stats', () =>
        HttpResponse.json({
          job_id: 'job-1',
          applications_total: 0,
          applications_by_status: {},
          matches_computed: 0,
          last_matched_at: null,
          extra: {},
        }),
      ),
      http.get('/api/v1/companies/:id/members', () => HttpResponse.json([])),
      http.patch('/api/v1/jobs/job-1', async ({ request }) => {
        patch = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          makeJobDetail({ id: 'job-1', status: 'PUBLISHED', title: String(patch.title) }),
        )
      }),
    )
    const { user } = renderApp('/manage/jobs/job-1/edit')
    expect(await screen.findByRole('heading', { name: /Edit “Senior Backend Engineer”/ })).toBeInTheDocument()
    expect(field(/job title/i)).toHaveValue('Senior Backend Engineer')
    expect(field(/department/i)).toHaveValue('Platform')
    expect(screen.getByText('This job is live')).toBeInTheDocument()
    // a live job has one save button (no draft/publish split)
    expect(screen.queryByRole('button', { name: 'Publish' })).not.toBeInTheDocument()

    await user.clear(field(/department/i))
    await user.clear(field(/job title/i))
    await paste(user, field(/job title/i), 'Staff Backend Engineer')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(patch.title).toBe('Staff Backend Engineer'))
    expect(patch.department).toBeNull() // cleared fields are sent as null so they really clear
    expect(patch.skills).toEqual([
      { skill_id: 'skill-python', requirement: 'REQUIRED', min_years: null },
      { skill_id: 'skill-postgresql', requirement: 'REQUIRED', min_years: 3 },
      { skill_id: 'skill-kubernetes', requirement: 'PREFERRED', min_years: null },
    ])
    expect(await screen.findByText('Candidate matches will refresh in the background.')).toBeInTheDocument()
  })

  it('closed jobs are read-only', async () => {
    signInAs('RECRUITER')
    server.use(
      http.get('/api/v1/jobs/job-1', () =>
        HttpResponse.json(
          makeJobDetail({ id: 'job-1', status: 'CLOSED', allowed_transitions: ['ARCHIVED'] }),
        ),
      ),
    )
    renderApp('/manage/jobs/job-1/edit')
    expect(await screen.findByText(/closed jobs can't be edited/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /save/i })).not.toBeInTheDocument()
  })
})
