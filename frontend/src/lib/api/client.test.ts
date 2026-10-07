import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { errorBody } from '@/test/fixtures'
import { server } from '@/test/server'
import { api, ApiError, buildQuery, onSessionExpired, refreshSession, tokenStore, upload } from '.'

describe('buildQuery', () => {
  it('repeats array params and drops empty values', () => {
    expect(
      buildQuery({
        skill: ['Python', 'SQL'],
        q: 'dev ops',
        page: 2,
        empty: '',
        none: undefined,
        nul: null,
        flag: false,
      }),
    ).toBe('?skill=Python&skill=SQL&q=dev+ops&page=2&flag=false')
    expect(buildQuery({})).toBe('')
    expect(buildQuery(undefined)).toBe('')
  })
})

describe('error normalisation', () => {
  it('turns the backend error envelope into an ApiError', async () => {
    server.use(
      http.get('/api/v1/boom', () =>
        HttpResponse.json(errorBody('JOB_NOT_FOUND', 'Job not found', { a: 1 }), { status: 404 }),
      ),
    )
    const err = await api.get('/boom').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({
      status: 404,
      code: 'JOB_NOT_FOUND',
      message: 'Job not found',
      details: { a: 1 },
      requestId: 'req-test',
    })
  })

  it('maps validation details to field errors and strips pydantic prefixes', async () => {
    server.use(
      http.post('/api/v1/x', () =>
        HttpResponse.json(
          errorBody('VALIDATION_ERROR', 'Request validation failed', [
            { field: 'title', message: 'String should have at least 3 characters', type: 'string_too_short' },
            {
              field: 'salary_max',
              message: 'Value error, salary_max must be >= salary_min',
              type: 'value_error',
            },
          ]),
          { status: 422 },
        ),
      ),
    )
    const err = (await api.post('/x', {}).catch((e: unknown) => e)) as ApiError
    expect(err.fieldErrors).toEqual({
      title: 'String should have at least 3 characters',
      salary_max: 'salary_max must be >= salary_min',
    })
  })

  it('exposes string detail lists (PUBLISH_VALIDATION_FAILED)', async () => {
    server.use(
      http.post('/api/v1/y', () =>
        HttpResponse.json(
          errorBody('PUBLISH_VALIDATION_FAILED', 'Cannot publish', ['Add at least one required skill']),
          { status: 422 },
        ),
      ),
    )
    const err = (await api.post('/y').catch((e: unknown) => e)) as ApiError
    expect(err.detailMessages).toEqual(['Add at least one required skill'])
    expect(err.is('PUBLISH_VALIDATION_FAILED')).toBe(true)
  })

  it('handles non-JSON gateway errors with a friendly message', async () => {
    server.use(http.get('/api/v1/gw', () => new HttpResponse('<html>Bad gateway</html>', { status: 502 })))
    const err = (await api.get('/gw').catch((e: unknown) => e)) as ApiError
    expect(err).toMatchObject({ status: 502, code: 'HTTP_502' })
    expect(err.message).toMatch(/temporarily unavailable/i)
  })

  it('reports network failures as status 0', async () => {
    server.use(http.get('/api/v1/down', () => HttpResponse.error()))
    const err = (await api.get('/down').catch((e: unknown) => e)) as ApiError
    expect(err).toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
    expect(err.isNetworkError).toBe(true)
  })

  it('returns undefined for 204', async () => {
    server.use(http.delete('/api/v1/gone', () => new HttpResponse(null, { status: 204 })))
    await expect(api.delete('/gone')).resolves.toBeUndefined()
  })
})

describe('authentication', () => {
  it('attaches the in-memory bearer token (never localStorage)', async () => {
    tokenStore.set('tok-123')
    let header: string | null = null
    server.use(
      http.get('/api/v1/me', ({ request }) => {
        header = request.headers.get('authorization')
        return HttpResponse.json({ ok: true })
      }),
    )
    await api.get('/me')
    expect(header).toBe('Bearer tok-123')
    expect(JSON.stringify({ ...localStorage })).not.toContain('tok-123')
  })

  it('on 401 silently refreshes ONCE and retries the request', async () => {
    tokenStore.set('expired')
    const seen: (string | null)[] = []
    let refreshes = 0
    server.use(
      http.get('/api/v1/private', ({ request }) => {
        const auth = request.headers.get('authorization')
        seen.push(auth)
        return auth === 'Bearer fresh'
          ? HttpResponse.json({ ok: 1 })
          : HttpResponse.json(errorBody('TOKEN_EXPIRED', 'Token has expired'), { status: 401 })
      }),
      http.post('/api/v1/auth/refresh', () => {
        refreshes++
        return HttpResponse.json({ access_token: 'fresh', token_type: 'bearer', expires_in: 900, user: {} })
      }),
    )
    await expect(api.get('/private')).resolves.toEqual({ ok: 1 })
    expect(seen).toEqual(['Bearer expired', 'Bearer fresh'])
    expect(refreshes).toBe(1)
    expect(tokenStore.get()).toBe('fresh')
  })

  it('shares one refresh between concurrent 401s (single-flight)', async () => {
    tokenStore.set('expired')
    let refreshes = 0
    server.use(
      http.get('/api/v1/a', ({ request }) =>
        request.headers.get('authorization') === 'Bearer fresh'
          ? HttpResponse.json({ a: 1 })
          : HttpResponse.json(errorBody('TOKEN_EXPIRED', 'x'), { status: 401 }),
      ),
      http.get('/api/v1/b', ({ request }) =>
        request.headers.get('authorization') === 'Bearer fresh'
          ? HttpResponse.json({ b: 1 })
          : HttpResponse.json(errorBody('TOKEN_EXPIRED', 'x'), { status: 401 }),
      ),
      http.post('/api/v1/auth/refresh', async () => {
        refreshes++
        await new Promise((r) => setTimeout(r, 30))
        return HttpResponse.json({ access_token: 'fresh', token_type: 'bearer', expires_in: 900, user: {} })
      }),
    )
    const [a, b] = await Promise.all([api.get('/a'), api.get('/b')])
    expect([a, b]).toEqual([{ a: 1 }, { b: 1 }])
    expect(refreshes).toBe(1)
  })

  it('when the refresh fails: signals session expiry and surfaces the 401', async () => {
    tokenStore.set('expired')
    const expired = vi.fn()
    const off = onSessionExpired(expired)
    server.use(
      http.get('/api/v1/private', () =>
        HttpResponse.json(errorBody('TOKEN_EXPIRED', 'Token has expired'), { status: 401 }),
      ),
    )
    const err = (await api.get('/private').catch((e: unknown) => e)) as ApiError
    off()
    expect(err).toMatchObject({ status: 401, code: 'TOKEN_EXPIRED' })
    expect(expired).toHaveBeenCalledTimes(1)
    expect(tokenStore.get()).toBeNull()
  })

  it('does not try to refresh for anonymous 401s', async () => {
    let refreshes = 0
    server.use(
      http.get('/api/v1/private', () =>
        HttpResponse.json(errorBody('UNAUTHORIZED', 'Not authenticated'), { status: 401 }),
      ),
      http.post('/api/v1/auth/refresh', () => {
        refreshes++
        return HttpResponse.json({}, { status: 401 })
      }),
    )
    await expect(api.get('/private')).rejects.toMatchObject({ status: 401 })
    expect(refreshes).toBe(0)
  })

  it('refreshSession resolves null when there is no valid session', async () => {
    await expect(refreshSession()).resolves.toBeNull()
  })
})

describe('upload (multipart with progress)', () => {
  it('posts FormData with the bearer token and reports completion', async () => {
    tokenStore.set('tok-up')
    let auth: string | null = null
    let name = ''
    server.use(
      http.post('/api/v1/resumes', async ({ request }) => {
        auth = request.headers.get('authorization')
        const form = await request.formData()
        name = (form.get('file') as File).name
        return HttpResponse.json({ id: 'r1' }, { status: 201 })
      }),
    )
    const progress: number[] = []
    const form = new FormData()
    form.append('file', new File(['hello'], 'cv.pdf', { type: 'application/pdf' }))
    const res = await upload<{ id: string }>('/resumes', form, { onProgress: (f) => progress.push(f) })
    expect(res).toEqual({ id: 'r1' })
    expect(auth).toBe('Bearer tok-up')
    expect(name).toBe('cv.pdf')
    expect(progress[progress.length - 1]).toBe(1)
  })

  it('normalises upload errors and retries once after a silent refresh', async () => {
    tokenStore.set('old')
    let attempts = 0
    server.use(
      http.post('/api/v1/resumes', ({ request }) => {
        attempts++
        return request.headers.get('authorization') === 'Bearer fresh'
          ? HttpResponse.json(errorBody('UNSUPPORTED_MEDIA_TYPE', 'Only PDF and DOCX files are accepted'), {
              status: 415,
            })
          : HttpResponse.json(errorBody('TOKEN_EXPIRED', 'expired'), { status: 401 })
      }),
      http.post('/api/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'fresh', token_type: 'bearer', expires_in: 900, user: {} }),
      ),
    )
    const err = (await upload('/resumes', new FormData()).catch((e: unknown) => e)) as ApiError
    expect(attempts).toBe(2)
    expect(err).toMatchObject({
      status: 415,
      code: 'UNSUPPORTED_MEDIA_TYPE',
      message: 'Only PDF and DOCX files are accepted',
    })
  })
})
