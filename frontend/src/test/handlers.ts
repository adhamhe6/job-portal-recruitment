import { http, HttpResponse } from 'msw'
import { errorBody, makeJobDetail, makeJobListItem, makeNotification, page, skill } from './fixtures'

const API = '/api/v1'

/**
 * Default MSW handlers: a signed-out visitor browsing a small catalogue. Tests override per-case with `server.use(...)`.
 * (`/auth/refresh` answers 401 by default = "no session"; use `signInAs(role)` from test-utils to change that.)
 */
export const handlers = [
  http.post(`${API}/auth/refresh`, () =>
    HttpResponse.json(errorBody('INVALID_REFRESH_TOKEN', 'Session expired'), { status: 401 }),
  ),
  http.get(`${API}/meta`, () => HttpResponse.json(errorBody('NOT_FOUND', 'Not Found'), { status: 404 })),
  http.get(`${API}/search/jobs`, () =>
    HttpResponse.json(
      page([
        makeJobListItem({ id: 'job-1', title: 'Senior Backend Engineer' }),
        makeJobListItem({ id: 'job-2', title: 'Frontend Engineer', company_name: 'Orbit Finance' }),
      ]),
    ),
  ),
  http.get(`${API}/jobs/:id`, ({ params }) => HttpResponse.json(makeJobDetail({ id: String(params.id) }))),
  http.get(`${API}/skills`, ({ request }) => {
    const q = new URL(request.url).searchParams.get('q')?.toLowerCase() ?? ''
    const all = ['Python', 'PostgreSQL', 'Kubernetes', 'React'].map((n) => skill(n))
    return HttpResponse.json(page(all.filter((s) => s.name.toLowerCase().includes(q))))
  }),
  http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ unread: 2 })),
  http.get(`${API}/notifications`, () =>
    HttpResponse.json(page([makeNotification({ id: 'n1' }), makeNotification({ id: 'n2', is_read: true })])),
  ),
  http.get(`${API}/companies/:id`, ({ params }) =>
    HttpResponse.json({ id: params.id, name: 'Northwind Labs', slug: 'northwind-labs' }),
  ),
]
