import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, type RenderResult } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { ReactElement, ReactNode } from 'react'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuthProvider } from '@/features/auth/components/AuthProvider'
import type { Role } from '@/lib/api'
import { createQueryClient } from '@/lib/queryClient'
import { routes } from '@/routes'
import { makeUser, tokenFor } from './fixtures'
import { server } from './server'

/** Make the silent refresh succeed as `role`, i.e. the app boots into a signed-in session. */
export function signInAs(role: Role, overrides: Parameters<typeof makeUser>[1] = {}) {
  const user = makeUser(role, overrides)
  server.use(http.post('/api/v1/auth/refresh', () => HttpResponse.json(tokenFor(user))))
  return user
}

function Providers({ children, client }: { children: ReactNode; client: ReturnType<typeof createQueryClient> }) {
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <TooltipProvider>{children}</TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

function testClient() {
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0, gcTime: Infinity }, mutations: { retry: false } })
  return client
}

/** Render the REAL route table at `url` with auth + query providers (the integration-style entry point). */
export function renderApp(url: string): RenderResult & { router: ReturnType<typeof createMemoryRouter>; user: ReturnType<typeof userEvent.setup> } {
  const client = testClient()
  const router = createMemoryRouter(routes, { initialEntries: [url] })
  const result = render(
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return { ...result, router, user: userEvent.setup() }
}

/** Render one component inside providers + a MemoryRouter (component-level tests). */
export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const client = testClient()
  const result = render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </Providers>,
  )
  return { ...result, client, user: userEvent.setup() }
}

/** Wait until the boot spinner is gone. */
export const waitForBoot = () => waitFor(() => expect(screen.queryByText(/Loading TalentLens/i)).not.toBeInTheDocument())
