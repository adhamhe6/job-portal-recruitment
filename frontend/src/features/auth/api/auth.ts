import { api, type ChangePasswordRequest, type Me, type RegisterCandidateRequest, type RegisterEmployerRequest, type TokenResponse, type UpdateMeRequest } from '@/lib/api'

/** Raw auth endpoints. Session state itself is managed by AuthProvider (useAuth), not by TanStack Query. */
export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { email, password }, { credentials: 'include', skipRefresh: true }),
  registerCandidate: (data: RegisterCandidateRequest) =>
    api.post<TokenResponse>('/auth/register', data, { credentials: 'include', skipRefresh: true }),
  registerEmployer: (data: RegisterEmployerRequest) =>
    api.post<TokenResponse>('/auth/register/employer', data, { credentials: 'include', skipRefresh: true }),
  logout: () => api.post<{ message: string }>('/auth/logout', undefined, { credentials: 'include', skipRefresh: true }),
  me: () => api.get<Me>('/auth/me'),
  updateMe: (data: UpdateMeRequest) => api.patch<Me>('/auth/me', data),
  changePassword: (data: ChangePasswordRequest) => api.post<{ message: string }>('/auth/change-password', data, { credentials: 'include' }),
}
