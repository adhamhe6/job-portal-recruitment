import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { errorBody, makeUser } from '@/test/fixtures'
import { server } from '@/test/server'
import { renderApp, signInAs } from '@/test/test-utils'

describe('account settings', () => {
  it('updates name and phone with PATCH /auth/me and confirms', async () => {
    signInAs('CANDIDATE')
    let body: unknown
    server.use(
      http.patch('/api/v1/auth/me', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(makeUser('CANDIDATE', { first_name: 'Alexandra', phone: '+49 30 123456' }))
      }),
    )
    const { user } = renderApp('/settings')
    const first = await screen.findByLabelText(/^first name/i)
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled() // nothing changed yet
    await user.clear(first)
    await user.type(first, 'Alexandra')
    await user.type(screen.getByLabelText(/^phone/i), '+49 30 123456')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(body).toEqual({ first_name: 'Alexandra', last_name: 'Rivera', phone: '+49 30 123456' }))
    expect(await screen.findByText('Account details updated')).toBeInTheDocument()
  })

  it('validates names and phone numbers, and maps server errors', async () => {
    signInAs('CANDIDATE')
    server.use(
      http.patch('/api/v1/auth/me', () =>
        HttpResponse.json(errorBody('VALIDATION_ERROR', 'Request validation failed', [{ field: 'phone', message: 'Value error, Enter a valid phone number', type: 'value_error' }]), { status: 422 }),
      ),
    )
    const { user } = renderApp('/settings')
    const first = await screen.findByLabelText(/^first name/i)
    await user.clear(first)
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Enter your first name')).toBeInTheDocument()
    await user.type(first, 'Alex')
    await user.type(screen.getByLabelText(/^phone/i), '+49 30 1234')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Enter a valid phone number')).toBeInTheDocument()
  })

  it('changing the password signs the user out everywhere and sends them to /login', async () => {
    signInAs('CANDIDATE')
    let body: unknown
    server.use(
      http.post('/api/v1/auth/change-password', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ message: 'Password updated; please sign in again' })
      }),
      http.post('/api/v1/auth/logout', () => HttpResponse.json({ message: 'ok' })),
    )
    const { user, router } = renderApp('/settings')
    await user.type(await screen.findByLabelText(/^current password/i, { selector: 'input' }), 'DemoPass123!')
    await user.type(screen.getByLabelText(/^new password/i, { selector: 'input' }), 'EvenBetter456')
    await user.type(screen.getByLabelText(/^confirm new password/i, { selector: 'input' }), 'EvenBetter456')
    await user.click(screen.getByRole('button', { name: 'Update password' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
    expect(body).toEqual({ current_password: 'DemoPass123!', new_password: 'EvenBetter456' })
  })

  it('rejects weak or mismatched new passwords on the client', async () => {
    signInAs('CANDIDATE')
    const { user } = renderApp('/settings')
    await user.type(await screen.findByLabelText(/^current password/i, { selector: 'input' }), 'DemoPass123!')
    await user.type(screen.getByLabelText(/^new password/i, { selector: 'input' }), 'onlyletters')
    await user.type(screen.getByLabelText(/^confirm new password/i, { selector: 'input' }), 'different')
    await user.click(screen.getByRole('button', { name: 'Update password' }))
    expect(await screen.findByText('Include at least one number')).toBeInTheDocument()
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
  })

  it('shows the server message when the current password is wrong', async () => {
    signInAs('CANDIDATE')
    server.use(http.post('/api/v1/auth/change-password', () => HttpResponse.json(errorBody('INVALID_CREDENTIALS', 'Current password is incorrect'), { status: 401 })))
    const { user } = renderApp('/settings')
    await user.type(await screen.findByLabelText(/^current password/i, { selector: 'input' }), 'wrongpass1')
    await user.type(screen.getByLabelText(/^new password/i, { selector: 'input' }), 'EvenBetter456')
    await user.type(screen.getByLabelText(/^confirm new password/i, { selector: 'input' }), 'EvenBetter456')
    await user.click(screen.getByRole('button', { name: 'Update password' }))
    expect(await screen.findByText('Current password is incorrect')).toBeInTheDocument()
  })

  it('theme: system by default, explicit dark applies the class and persists', async () => {
    signInAs('CANDIDATE')
    const { user } = renderApp('/settings')
    expect(await screen.findByRole('radio', { name: /System/ })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: /Dark/ }))
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('talentlens.theme')).toBe('dark')
    await user.click(screen.getByRole('radio', { name: /Light/ }))
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('shows Company/Team sections only to staff that can manage the company', async () => {
    signInAs('CANDIDATE')
    const cand = renderApp('/settings')
    await screen.findByRole('heading', { name: 'Settings' })
    expect(screen.queryByRole('link', { name: 'Company' })).not.toBeInTheDocument()
    cand.unmount()
    signInAs('RECRUITER')
    renderApp('/settings')
    expect(await screen.findByRole('link', { name: 'Company' })).toHaveAttribute('href', '/settings/company')
    expect(screen.getByRole('link', { name: 'Team' })).toHaveAttribute('href', '/settings/team')
  })
})
