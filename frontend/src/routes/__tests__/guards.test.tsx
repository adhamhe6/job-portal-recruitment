import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Role } from '@/lib/api'
import { renderApp, signInAs, waitForBoot } from '@/test/test-utils'

const mainNav = () => within(screen.getByRole('navigation', { name: 'Main' }))
const navLabels = () =>
  mainNav()
    .getAllByRole('link')
    .map((a) =>
      (a.getAttribute('aria-label') ?? a.textContent ?? '')
        .replace(/\d+$/, '')
        .replace(/, \d+ unread/, '')
        .trim(),
    )

const EXPECTED_NAV: Record<Role, string[]> = {
  CANDIDATE: [
    'Dashboard',
    'Find Jobs',
    'Recommended Jobs',
    'Applications',
    'Interviews',
    'Résumé',
    'Profile',
    'Notifications',
    'Settings',
  ],
  RECRUITER: [
    'Dashboard',
    'Jobs',
    'Candidates',
    'Applications',
    'Interviews',
    'Candidate Matching',
    'Reports',
    'Notifications',
    'Settings',
  ],
  HIRING_MANAGER: [
    'Dashboard',
    'Jobs',
    'Applications',
    'Interviews',
    'Candidate Matching',
    'Notifications',
    'Settings',
  ],
  ADMIN: [
    'Dashboard',
    'Users',
    'Companies',
    'Jobs',
    'Applications',
    'System Monitoring',
    'Reports',
    'Settings',
  ],
}

describe('role-specific navigation', () => {
  it.each(Object.entries(EXPECTED_NAV) as [Role, string[]][])(
    '%s sees exactly their navigation',
    async (role, labels) => {
      signInAs(role)
      renderApp('/dashboard')
      await waitForBoot()
      await screen.findByRole('navigation', { name: 'Main' })
      expect(navLabels()).toEqual(labels)
    },
  )

  it('marks the current page in the sidebar', async () => {
    signInAs('RECRUITER')
    renderApp('/manage/jobs')
    await screen.findByRole('navigation', { name: 'Main' })
    expect(mainNav().getByRole('link', { name: 'Jobs' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('route guards', () => {
  it('shows an in-place 403 for a candidate opening a staff page (URL preserved)', async () => {
    signInAs('CANDIDATE')
    const { router } = renderApp('/manage/jobs')
    expect(await screen.findByText(/you don't have access to this page/i)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/manage/jobs')
  })

  it('shows a 403 for staff opening a candidate-only page', async () => {
    signInAs('RECRUITER')
    renderApp('/recommended')
    expect(await screen.findByText(/you don't have access to this page/i)).toBeInTheDocument()
  })

  it('hiring managers can list jobs but not create them (permission manage_jobs)', async () => {
    signInAs('HIRING_MANAGER')
    const first = renderApp('/manage/jobs/new')
    expect(await screen.findByText(/you don't have access to this page/i)).toBeInTheDocument()
    first.unmount()
    signInAs('HIRING_MANAGER')
    renderApp('/manage/jobs')
    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
  })

  it('only admins reach /admin/*', async () => {
    signInAs('RECRUITER')
    const rec = renderApp('/admin/users')
    expect(await screen.findByText(/you don't have access to this page/i)).toBeInTheDocument()
    rec.unmount()
    signInAs('ADMIN')
    renderApp('/admin/users')
    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
  })

  it('the saved-jobs tab requires a candidate account', async () => {
    const anon = renderApp('/jobs/saved')
    await screen.findByRole('heading', { name: 'Welcome back' })
    expect(anon.router.state.location.pathname).toBe('/login')
  })

  it.each<[Role, string, string]>([
    ['CANDIDATE', '/dashboard', 'Dashboard'],
    ['CANDIDATE', '/recommended', 'Recommended jobs'],
    ['CANDIDATE', '/applications', 'My applications'],
    ['CANDIDATE', '/applications/abc', 'Application'],
    ['CANDIDATE', '/interviews', 'My interviews'],
    ['CANDIDATE', '/resume', 'Résumé'],
    ['CANDIDATE', '/profile', 'Profile'],
    ['RECRUITER', '/dashboard', 'Dashboard'],
    ['RECRUITER', '/candidates', 'Candidates'],
    ['RECRUITER', '/candidates/abc', 'Candidate'],
    ['RECRUITER', '/applications', 'Applications'],
    ['RECRUITER', '/interviews', 'Interviews'],
    ['RECRUITER', '/matching', 'Candidate matching'],
    ['RECRUITER', '/matching/abc', 'Candidate matching'],
    ['RECRUITER', '/reports', 'Reports'],
    ['RECRUITER', '/settings/company', 'Company settings'],
    ['RECRUITER', '/settings/team', 'Team'],
    ['ADMIN', '/dashboard', 'Dashboard'],
    ['ADMIN', '/admin/companies', 'Companies'],
    ['ADMIN', '/admin/system', 'System monitoring'],
  ])('%s: %s renders an honest placeholder (route table is wired)', async (role, url, title) => {
    signInAs(role)
    renderApp(url)
    expect(await screen.findByRole('heading', { name: title, level: 1 })).toBeInTheDocument()
    expect(screen.getByText(/under construction/i)).toBeInTheDocument()
  })

  it('unknown URLs get a friendly 404', async () => {
    renderApp('/definitely/not/here')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Browse jobs' })).toBeInTheDocument())
  })
})
