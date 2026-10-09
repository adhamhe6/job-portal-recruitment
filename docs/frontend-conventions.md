# TalentLens frontend — conventions & handbook

Everything a feature engineer needs to add pages to `frontend/` without touching the foundation (router, shell, API
client, shared components). Wave 1 built the foundation and the whole **Jobs** domain; wave 2 fills in the other areas
by replacing page modules listed in [§3](#3-wave-2-page-files-owned-by-others).

- [1. Stack, commands, layout](#1-stack-commands-layout)
- [2. How to add a page or feature](#2-how-to-add-a-page-or-feature)
- [3. Wave-2 page files (owned by others)](#3-wave-2-page-files-owned-by-others)
- [4. API client](#4-api-client)
- [5. Data fetching: query keys & hooks](#5-data-fetching-query-keys--hooks)
- [6. Auth, roles, permissions, guards](#6-auth-roles-permissions-guards)
- [7. Forms](#7-forms)
- [8. Error handling](#8-error-handling)
- [9. Testing](#9-testing)
- [10. Theming & design tokens](#10-theming--design-tokens)
- [11. Component catalogue](#11-component-catalogue)
- [12. Accessibility & performance checklist](#12-accessibility--performance-checklist)
- [13. Visual QA and the real-stack smoke test](#13-visual-qa-and-the-real-stack-smoke-test)
- [14. Backend notes the frontend relies on](#14-backend-notes-the-frontend-relies-on)

---

## 1. Stack, commands, layout

React 19 · TypeScript (strict) · Vite 8 · Tailwind v4 · Radix primitives (shadcn-style components we own) · TanStack
Query 5 · React Hook Form + zod · react-router 7 (data router) · Recharts · sonner · lucide · date-fns · Vitest + Testing
Library + MSW · ESLint (typescript-eslint, react-hooks, jsx-a11y) + Prettier.

| Command | What it does |
|---|---|
| `npm run dev` | Vite on :5173; `/api`, `/docs`, `/openapi.json`, `/health` are proxied to `http://localhost:8000` (override `VITE_API_PROXY`). Same-origin, so the HttpOnly `SameSite=Strict` refresh cookie works. |
| `npm run gen:api` | `openapi-typescript` → `src/lib/api/schema.d.ts` (`OPENAPI_URL` overrides the source). **Commit the result** whenever the backend schema changes. |
| `npm run lint` / `lint:fix` | ESLint (zero warnings expected). |
| `npm run format` / `format:check` | Prettier. |
| `npm run typecheck` | `tsc -b --noEmit`. |
| `npm test` | Vitest (jsdom + MSW). `test:watch`, `test:coverage` also exist. |
| `npm run build` | `tsc -b && vite build`. Output in `dist/`. |
| `node scripts/screenshots.mjs` | Playwright visual QA (see §13). |
| `node scripts/e2e-smoke.mjs` | Real-stack smoke test (see §13). |

Production: `Dockerfile` (node build → nginx) + `nginx.conf` (SPA fallback, proxies `/api/`, `/docs`, `/openapi.json`,
`/health` to `http://api:8000`, gzip, immutable caching for `/assets/`, security headers, `client_max_body_size 12m`,
`X-Forwarded-*`). Build arg `VITE_SHOW_DEMO_ACCOUNTS=true` bakes the demo-login shortcuts in (see §14).

```
src/
  main.tsx, App.tsx          providers: QueryClient → AuthProvider → Tooltip → RouterProvider (+ Toaster)
  index.css                  design tokens (CSS variables), Tailwind theme, base styles
  routes/                    paths.ts (URL helpers) · index.tsx (THE route table) · lazy.tsx (lazyPage, roleSwitch)
  components/
    ui/                      primitives (Radix/shadcn style): Button, Input, Select, Dialog, Sheet, Table, …
    common/                  composed, app-aware pieces: PageHeader, DataTable, States, StatusBadge, MatchScore, …
    layout/                  AppShell, Sidebar, PublicLayout, AuthLayout, AdaptiveLayout, nav.ts
  features/<domain>/
    api/                     query keys + hooks (+ raw endpoint fns)       e.g. features/jobs/api/jobs.ts
    components/              domain components                              e.g. JobCard, ApplyDialog
    pages/                   route-level pages, default-exported            e.g. JobSearchPage.tsx
    hooks/  lib/             domain hooks / pure helpers (filters, schemas, mappers)
    __tests__/               domain tests
  lib/                       api/ (client, errors, query, types, generated schema), format.ts, enums.ts, forms.ts,
                             permissions.ts, theme.ts, queryClient.ts, utils.ts
  hooks/                     useUrlState, useDebouncedValue, useMediaQuery, useDocumentTitle
  pages/                     NotFound, Forbidden, RouteError
  test/                      setup.ts, server.ts (MSW), handlers.ts, fixtures.ts, test-utils.tsx
```

Rules of thumb: `@/` is `src/`; **no `any`**; API types come from `@/lib/api` (generated), never hand-written unless the
endpoint is not in the schema yet (then declare the minimal shape next to the hook and say so, see
`features/resumes/api/resumes.ts`); user-visible numbers/dates go through `@/lib/format`; enum labels live in
`@/lib/enums`; URLs go through `@/routes/paths`.

---

## 2. How to add a page or feature

**Replace a wave-2 stub** (the common case): open the page file from §3, keep the `export default` component, delete
`<UnderConstruction/>`. The route, navigation entry, guard and layout already exist. Start with:

```tsx
// src/features/applications/pages/MyApplicationsPage.tsx
import { PageHeader } from '@/components/common/PageHeader'
import { DataTable } from '@/components/common/DataTable'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { useMyApplications } from '../api/applications'

export default function MyApplicationsPage() {
  useDocumentTitle('My applications')
  const [{ status, page }, update] = useUrlState({ status: '', page: 1 })   // filters live in the URL
  const query = useMyApplications({ status, page })                           // hook in ../api/applications.ts
  return (
    <>
      <PageHeader title="My applications" description="…" />
      <DataTable caption="Applications" rows={query.data?.items} loading={query.isFetching} error={query.error} … />
    </>
  )
}
```

**Add a brand-new route** (rare): (1) add a helper to `routes/paths.ts`; (2) add one entry to `routes/index.tsx`, inside
the right layout/guard group, using `lazyPage(() => import('…'))`; (3) if it belongs in the sidebar, add it to
`components/layout/nav.ts`. Nothing else changes.

**Add a feature module**: create `features/<domain>/{api,components,pages}`; put query keys and hooks in `api/`; keep
pages thin (compose hooks + components); add tests in `__tests__/`; register fixtures in `src/test/fixtures.ts` if
other domains' tests will need them.

**Extend an existing API module** (e.g. you need `GET /applications`): add your hooks to `features/applications/api/applications.ts`
(it currently only has `useApplyToJob`, used by the apply dialog) and keep the existing export.

Role-dependent URLs (`/dashboard`, `/applications`, `/interviews`) use `roleSwitch({ CANDIDATE: () => import(…), … })`
in the route table: one URL, one page file per audience.

---

## 3. Wave-2 page files (owned by others)

Each renders `<UnderConstruction/>` today. **Replace the file contents; do not touch the router, nav, shell or shared
components.** Routes are guarded as listed (`RequireAuth`; others get an in-place 403).

| Page module (`src/features/…`) | Route | Audience | Expected API |
|---|---|---|---|
| `dashboard/pages/CandidateDashboardPage.tsx` | `/dashboard` | CANDIDATE | `GET /applications`, `GET /recommendations/jobs`, `GET /candidates/me/completion`, `GET /interviews`, `GET /notifications` |
| `dashboard/pages/RecruiterDashboardPage.tsx` | `/dashboard` | RECRUITER, HIRING_MANAGER | `GET /jobs` (+`/jobs/{id}/stats`), `GET /applications`, `GET /interviews`, `GET /reports/*` |
| `dashboard/pages/AdminDashboardPage.tsx` | `/dashboard` | ADMIN | `GET /reports/admin/*`, `GET /admin/*`, `GET /health/ready` |
| `recommendations/pages/RecommendedJobsPage.tsx` | `/recommended` | CANDIDATE | `GET /recommendations/jobs` (`items[].job` is a `JobListItem` → reuse `JobCard` with `matchPercent`/`matchBand`; `items[].match` is a `CandidateFacingMatch` → reuse `MatchExplanation`), `POST /recommendations/refresh`, `GET /tasks/{id}` |
| `applications/pages/MyApplicationsPage.tsx` | `/applications` | CANDIDATE | `GET /applications`, `POST /applications/{id}/withdraw` |
| `applications/pages/ApplicationsPage.tsx` | `/applications` | RECRUITER, HIRING_MANAGER, ADMIN | `GET /applications` (`job_id`, `status`, `q`, `sort`; the Jobs pages link here with `?job_id=`), `POST /applications/{id}/status` |
| `applications/pages/ApplicationDetailPage.tsx` | `/applications/:id` | all roles | `GET /applications/{id}`, `/history`, `/notes`, `POST …/notes`, `POST …/status`, `POST …/withdraw` |
| `interviews/pages/MyInterviewsPage.tsx` | `/interviews` | CANDIDATE | `GET /interviews` |
| `interviews/pages/InterviewsPage.tsx` | `/interviews` | staff, ADMIN | `GET/POST /interviews`, feedback endpoints |
| `interviews/pages/InterviewDetailPage.tsx` | `/interviews/:id` | all roles | `GET /interviews/{id}`, status/feedback actions (notifications deep-link here) |
| `resumes/pages/ResumePage.tsx` | `/resume` | CANDIDATE | `GET/POST /resumes` (use `upload()` from `@/lib/api` + `FileDropzone`), `GET /tasks/{id}`; extend `features/resumes/api/resumes.ts` (`useMyResumes` is used by the apply dialog) |
| `profile/pages/ProfilePage.tsx` | `/profile` | CANDIDATE | `GET/PATCH /candidates/me`, experiences/educations/certifications/languages/skills sub-resources, `GET /candidates/me/completion` |
| `candidates/pages/CandidatesPage.tsx` | `/candidates` | RECRUITER, HIRING_MANAGER, ADMIN | `GET /search/candidates` (`SkillPicker`, `useUrlState`, `MatchScoreBadge`) |
| `candidates/pages/CandidateDetailPage.tsx` | `/candidates/:id` | staff | `GET /candidates/{id}?job_id=` |
| `matching/pages/MatchingPage.tsx` | `/matching`, `/matching/:jobId` | staff | `GET /matches/jobs/{id}/candidates`, `POST /matches/jobs/{id}/refresh` (202 + task), `GET …/candidates/{cid}`. Notifications of type `NEW_CANDIDATE_MATCH` and the job pages link to `/matching/:jobId`; `/matching` (no id) should offer a job picker (`useManagedJobs`). |
| `reports/pages/ReportsPage.tsx` | `/reports` | `view_reports` permission | `GET /reports/*` (use `ChartCard`, `KpiCard`, `chartTheme`) |
| `admin/pages/UsersPage.tsx` | `/admin/users` | ADMIN | `GET/POST /users`, `PATCH /users/{id}` |
| `admin/pages/CompaniesPage.tsx` | `/admin/companies` | ADMIN | `GET/POST /companies`, `PATCH /companies/{id}` |
| `admin/pages/SystemMonitoringPage.tsx` | `/admin/system` | ADMIN | `GET /health/ready`, `GET /admin/*` |
| `company/pages/CompanySettingsPage.tsx` | `/settings/company` | `manage_own_company` | `GET /companies/me`, `PATCH /companies/{id}` (renders inside `SettingsLayout`; page content only) |
| `company/pages/TeamSettingsPage.tsx` | `/settings/team` | `manage_own_company` | `GET/POST/PATCH /companies/{id}/members` (`useCompanyMembers` exists in `features/companies/api/companies.ts`) |

Owned by wave 1 (do not replace; extend through hooks if needed): `home`, `auth` (login/register/employer), `jobs/*`
(search, saved, detail, manage list, create/edit form), `notifications`, `settings/pages/AccountSettingsPage`.

Hooks other areas can reuse today: `useJobSearch`, `useManagedJobs`, `useJob`, `useJobStats`, `useSavedJobs`,
`useToggleSaveJob`, `useJobLifecycle` (confirm dialogs), `useMyJobMatch`, `useCompany`, `useCompanyMembers`,
`useSkillSearch`, `useMyResumes`, `useApplyToJob`, `useNotifications`, `useUnreadCount`. Components: `JobCard`,
`JobResults`, `MatchExplanation`, `SkillPicker`/`SkillTagInput`, `CompanyLogo`.

---

## 4. API client

`src/lib/api` (import everything from `@/lib/api`).

```ts
import { api, upload, ApiError, type JobListItem, type Paginated } from '@/lib/api'

const page = await api.get<Paginated<JobListItem>>('/search/jobs', { skill: ['Python', 'SQL'], page: 2 })
await api.post<JobDetail>('/jobs', body)                       // JSON body
await api.post('/jobs', body, { query: { company_id } })       // query string on a POST
await api.patch('/auth/me', { first_name: 'Ada' })
await api.put('/jobs/1/save'); await api.delete('/jobs/1/save')
await upload<ResumeOut>('/resumes', formData, { onProgress: (f) => setProgress(f) })   // XHR, progress 0..1, same 401 handling
await downloadFile('/resumes/1/file', undefined, 'resume.pdf')                         // authenticated download
```

- Paths are relative to `/api/v1` (`VITE_API_BASE_URL`). Query values: arrays become repeated params
  (`skill=a&skill=b`), `null | undefined | ''` are dropped.
- **Token**: access token lives in memory only (`tokenStore`). The refresh token is the HttpOnly cookie.
- **401 handling**: a 401 on an authenticated request triggers one silent, single-flight `POST /auth/refresh`
  (`credentials: 'include'`, Web-Locks-serialised across tabs, `keepalive` so a reload during a refresh cannot trigger
  reuse detection), then the request is retried once. If refresh fails: `onSessionExpired` listeners fire
  (`AuthProvider` clears the session → guards redirect to `/login?next=…`) and the original 401 is thrown.
  Auth endpoints (`/auth/login|register|refresh`) never trigger a refresh.
- **Errors**: every failure is an `ApiError { status, code, message, details, requestId }`. Helpers: `err.is('CODE')`,
  `err.fieldErrors` (`{ field: message }` from 422 `details[]`, pydantic prefixes stripped), `err.fieldIssues`,
  `err.detailMessages` (string-list details, e.g. `PUBLISH_VALIDATION_FAILED`), `err.isNetworkError` (status 0).
  `errorMessage(e)` is the safe string for any `unknown`.
- **Types**: `@/lib/api/types.ts` aliases the generated schema (`JobListItem`, `Me`, `Paginated<T>`, …). Add aliases
  there as you need them. Decimals come back as **strings** (`"90000.00"`) and are accepted as numbers on input.
- Session events: `onSessionExpired(fn)`, `onSessionRefreshed(fn)`, `refreshSession()`.

---

## 5. Data fetching: query keys & hooks

TanStack Query defaults (`lib/queryClient.ts`): `staleTime` 30 s, no refetch on window focus, no retry on 4xx, 2 retries
otherwise. Use `placeholderData: keepPreviousData` for paginated/filtered lists so the old page stays visible (dimmed)
while the next loads.

**Key convention**: a domain root segment, then kind, then params object — `['jobs', 'search', filters]`,
`['jobs', 'detail', id]`, `['notifications', 'unread-count']`. Export a `…Keys` object from the domain's `api/` module and
use only that. One `invalidateQueries({ queryKey: ['jobs'] })` refreshes everything job-related after a mutation.

**Hook shape**: one hook per endpoint, `queryFn: ({ signal }) => api.get(…, …, { signal })` (cancellation for free),
`enabled` for dependent queries. Resolve "absence is normal" cases in the hook (e.g. `useMyJobMatch` returns `null` on
404) rather than in every component.

**Mutations**: `onMutate` for optimistic UI (cancel queries, snapshot, patch the cache with `setQueriesData`), `onError`
rolls back from the snapshot, `onSettled`/`onSuccess` invalidates. See `useToggleSaveJob` and `useMarkRead`.

**No waterfalls**: start independent queries in the page component in parallel (the job page starts job + match + stats
together; child components reuse the same keys). Do not gate a query on another query's *data* unless it truly needs it.

**URL is the state for lists**: `useUrlState(defaults)` returns `[state, update, reset]`; defaults are omitted from the
URL, arrays serialise as repeated params, `update()` resets `page` unless you pass `{ resetPage: false }`.

---

## 6. Auth, roles, permissions, guards

```tsx
const { user, status, can, hasRole, isCandidate, isStaff, isAdmin, login, logout } = useAuth()
if (can('manage_jobs')) …            // permission strings come from GET /auth/me (typed in lib/permissions.ts)
const me = useCurrentUser()          // inside <RequireAuth>: non-null user
```

- `AuthProvider` blocks rendering until one silent refresh decides "signed in or not", so no query ever runs with the
  wrong identity. It clears the query cache on login/logout/expiry (never leak one user's data to the next).
- **Prefer permissions over roles** for feature gating (`can('view_reports')`); use roles for layout/audience.
- Guards (route table): `<RequireAuth roles={[…]} permission="…" />` (layout route; renders `<Outlet/>`) — anonymous →
  `/login?next=<path>`, wrong role/permission → in-place 403 page. `<RequireGuest/>` wraps login/register.
- Navigation per role is `components/layout/nav.ts` (`NAV_BY_ROLE`).
- Public-but-personalised pages (`/jobs`, `/jobs/:id`) render in `AdaptiveLayout` (marketing layout for visitors, app
  shell for members). Use `<PageContainer>` for page width/padding that must work in both.
- Backend object-level rules are the source of truth: the UI hides what a role cannot do, but always handle 403/404.

---

## 7. Forms

Pattern: **React Hook Form + zod resolver + `Field` + `applyApiErrors`**.

```tsx
const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues, mode: 'onTouched' })
const { register, handleSubmit, setError, control, formState: { errors, isSubmitting, isDirty } } = form

const onSubmit = handleSubmit(async (values) => {
  try { await mutation.mutateAsync(toPayload(values)) }
  catch (e) {
    setFormError(applyApiErrors(e, setError, {
      fields: ['title', 'email'],                                  // form field names
      codeFields: { EMAIL_ALREADY_REGISTERED: 'email' },           // business error code → field
      inferField: (msg) => (msg.includes('salary_max') ? 'salary_max' : undefined),   // model-level validator errors
    }))                                                            // returns leftover message for a form-level <Alert>
    focusFirstError()
  }
}, () => focusFirstError())

<Field label="Title" error={errors.title?.message} required><Input {...register('title')} /></Field>
```

- Keep form values as **strings** for number/date inputs; convert in one `toPayload()` (see `features/jobs/lib/jobForm.ts`).
  Send explicit `null` to clear optional fields on PATCH.
- Client rules mirror `backend/app/schemas/*`; the server still validates and its field errors are mapped back.
- Use `useWatch({ control, name })` (not `watch()`), and call `submit` helpers from event handlers only (the
  React-Compiler lint rules flag render-time calls).
- Unsaved changes: `useBlocker` + `beforeunload` (see `JobFormPage`); remember to set an "allow leave" ref before
  navigating after a successful save.
- Combobox/async pickers are `useWatch`/`Controller`-friendly; `Field` accepts `htmlFor` for composite widgets.

---

## 8. Error handling

| Situation | Pattern |
|---|---|
| Query failed (list/page) | `<ErrorState error onRetry />` (retry also refetches other failed queries on screen); inside a card use `compact` |
| Query is "optional" (match, saved flag) | resolve to `null` in the hook; hide the UI; never show an error for expected 404s |
| Mutation failed (form) | map to fields with `applyApiErrors`, else `<Alert variant="danger">` at the top of the form |
| Mutation failed (confirm dialog) | keep the dialog open and render the explanation inside it (`describeLifecycleError`) |
| Fire-and-forget (toggle) | optimistic update + rollback + `toast.error(title, { description })` |
| 401 | handled by the client (refresh, else logout + redirect) — don't handle in components |
| 403 | route guard renders `ForbiddenPage`; for API 403 inside a page, `ErrorState` says "Access denied" |
| Unexpected render error | router `errorElement` (`RouteError`), including "new version available" for failed lazy chunks |

Always give a **plain-language** message (see `describeLifecycleError`, `applyErrorMessage` in the apply dialog) and a
next step. Show `requestId` ("Reference: …") for 5xx so support can find the log line.

---

## 9. Testing

Vitest + Testing Library + MSW (`src/test`). `npm test` runs everything (≈ 240 tests).

- `server.ts` / `handlers.ts`: default handlers = a signed-out visitor with a tiny catalogue; unhandled requests **fail**
  the test. Override per test: `server.use(http.get('/api/v1/…', () => HttpResponse.json(…)))`.
- `fixtures.ts`: typed factories (`makeUser(role)`, `makeJobListItem`, `makeJobDetail`, `makeJobPublic`, `page()`,
  `makeNotification`, `errorBody(code, message, details)`).
- `test-utils.tsx`:
  - `signInAs('RECRUITER')` makes the boot-time silent refresh succeed as that role.
  - `renderApp('/jobs?q=x')` renders the **real route table** (providers, guards, layouts) and returns `{ user, router }`
    so tests assert on `router.state.location` (URL sync, redirects) and requests.
  - `renderWithProviders(ui)` for a single component.
- Assert what the **API received** (capture params/bodies in handlers) and what the **user sees** (roles/labels), not
  implementation details. Use `findBy…`/`waitFor` (lazy route chunks take a moment; `asyncUtilTimeout` is 6 s).
- Radix needs a few jsdom stubs (done in `setup.ts`); `useMediaQuery` falls back to *desktop* when `matchMedia` is absent;
  stub `window.matchMedia` in a test to exercise the mobile (card) layouts.
- Timers: fake only what you need (`vi.useFakeTimers({ toFake: ['setInterval'] })` for polling) so MSW still works.
- Each feature's tests live in `features/<domain>/__tests__/`. Cover: happy path, validation (client + server mapping),
  empty/error states, permission differences between roles.

---

## 10. Theming & design tokens

Tokens are CSS variables in `src/index.css` (`:root` = light, `.dark` = dark) exposed to Tailwind via `@theme inline`, so
use semantic utilities, **never raw palette colours for surfaces/text**:

`bg-background` `bg-card` `bg-surface` `bg-popover` `bg-muted` `bg-accent` `bg-primary` `bg-primary-soft`
`text-foreground` `text-muted-foreground` `text-primary` `text-primary-soft-foreground` `border-border` `border-input`
`ring-ring` `bg-destructive` `text-destructive` `bg-sidebar` … plus chart (`--chart-1..5`) and match-band
(`--band-strong|good|partial|weak`) tokens. Radius via `rounded-md|lg|xl` (base `--radius: 0.625rem`), shadows
`shadow-xs..xl`.

- Brand: indigo/violet primary on cool slate neutrals; Inter Variable (`@fontsource-variable/inter`).
- Dark mode: class `.dark` on `<html>`. Preference is `system` (default) | `light` | `dark`, stored in
  `localStorage['talentlens.theme']`; `public/theme-init.js` applies it before first paint (no flash; external file so a
  strict CSP works). Use `useTheme()` / `<ThemeToggle/>`.
- Contrast: text/surface pairs are tuned for ≥ 4.5:1 (3:1 for large text/UI) in both themes; status colours are paired
  with text/icons (never colour alone). Focus ring is a global `:focus-visible` outline in `--ring`.
- Motion: keyframes/animations are defined in the theme (`animate-fade-in`, `animate-pop-in`, `animate-slide-in-*`);
  `prefers-reduced-motion` disables them globally.
- Charts: use `ChartCard` + `chartTheme` (grid/axis/tooltip styling, `colors` in fixed order, never cycled). One series →
  `var(--chart-1)`. Bars ≤ 24 px with 4 px rounded data-ends, hairline grid, labels in text colours, plus a hidden
  data table for screen readers (see `JobOverview`).
- Layout gotcha: a bare `.grid` has a global single `minmax(0,1fr)` column (prevents phone overflow); `grid-cols-*`
  utilities still override it.

---

## 11. Component catalogue

### `components/ui` (primitives)

`Button` (`variant`: default·secondary·soft·outline·ghost·destructive·link; `size`: sm·default·lg·icon·icon-sm;
`loading`, `asChild`) · `Input`, `Textarea`, `NativeSelect` · `Select`/`SimpleSelect` (Radix) · `Combobox`, `MultiSelect`
(cmdk) · `Checkbox` · `Switch` · `RadioGroup` · `Label` · `Field` · `Badge` · `Alert` · `Card*` · `Tabs*` · `Dialog*` ·
`AlertDialog*` · `Sheet*` (left/right/bottom) · `DropdownMenu*` · `Popover*` · `Tooltip` · `Skeleton` · `Progress` ·
`Avatar` · `Separator` · `Table*` · `Pagination`.

```tsx
<Button loading={isPending} onClick={save}>Save</Button>
<Button asChild variant="outline"><Link to={paths.jobs}>Browse</Link></Button>

<Field label="Email" hint="Work address" error={errors.email?.message} required><Input type="email" {...register('email')} /></Field>

<Dialog open={open} onOpenChange={setOpen}>
  <DialogContent size="md">
    <DialogHeader><DialogTitle>Title</DialogTitle><DialogDescription>Why this dialog</DialogDescription></DialogHeader>
    …<DialogFooter><Button>OK</Button></DialogFooter>
  </DialogContent>
</Dialog>            // focus is trapped, Esc closes, focus returns to the opener (even without a DialogTrigger)

<Sheet><SheetTrigger asChild><Button>Filters</Button></SheetTrigger>
  <SheetContent side="right"><SheetHeader><SheetTitle>Filters</SheetTitle></SheetHeader><SheetBody>…</SheetBody></SheetContent></Sheet>

<Combobox value={v} onChange={setV} options={[{ value: 'a', label: 'Alpha' }]} aria-label="Letter" />
<MultiSelect values={vs} onChange={setVs} options={opts} />
<SimpleSelect value={v} onValueChange={setV} options={opts} emptyLabel="Any" />
<Pagination page={p} pages={n} total={t} pageSize={10} onPageChange={setP} label="jobs" />
```

### `components/common` (composed)

| Component | Use |
|---|---|
| `PageHeader` | `title`, `description`, `breadcrumbs=[{label,to}]`, `actions`, `meta`. Exactly one per page (the `<h1>`). |
| `EmptyState` / `NoResults` | Empty list with a useful `action`. |
| `ErrorState` / `InlineError` | Retryable error panel / compact form error. |
| `TableSkeleton`, `CardGridSkeleton`, `Spinner` | Loading placeholders. |
| `DataTable` | Responsive table: `columns`, `rows`, `rowKey`, `loading`, `error`, `empty`, `renderCard` (cards <768 px), `sortKey/sortDirection/onSortChange` (`aria-sort`), `page/pages/total/pageSize/onPageChange`, `caption` (required, a11y). |
| `SearchInput` | Debounced keyword box (`value`/`onChange` = committed value; Enter commits; clear button). |
| `DebouncedInput` | Debounced text/number input for filters. |
| `FilterBar` | Toolbar + removable active-filter chips + "Clear all". |
| `StatusBadge` | `kind="job" \| "application" \| "resume" \| "interview"` + `status`; text + dot, unknown statuses degrade. |
| `MatchScoreBadge`, `MatchBar` | `score` (0–1) or `percent` (0–100) + optional `band`; STRONG ≥ 0.75, GOOD ≥ 0.55, PARTIAL ≥ 0.35, else WEAK (same as backend). |
| `SkillChip`, `SkillChipList` | tones: `required`, `preferred`, `matched`, `missing`, `related`, `muted`; optional `onRemove`. |
| `KpiCard` | `label`, `value`, `hint`, `icon`, `tone`, `change`, `to`, `loading`. |
| `ChartCard` + `chartTheme` | Card shell for Recharts: title, description, loading, error, `srSummary`. |
| `Timeline` | Vertical events (application history). |
| `Stepper` | Horizontal progress (`steps`, `current`). |
| `FileDropzone` | Click/drag file picker with type/size validation, selected-file row and upload progress. |
| `ConfirmDialog` | Controlled `AlertDialog`; stays open while `loading`; accepts children for reasons/errors. |
| `CopyButton` | Clipboard copy with confirmation. |
| `PasswordInput`, `PasswordRules` | Show/hide toggle; live checklist of the backend password rules. |
| `TextBlock` | Safe rendering of multi-paragraph user text (paragraphs + `-` bullets, never HTML). |
| `Logo`, `LogoMark`, `UnderConstruction` | Brand mark; placeholder for unbuilt pages. |

### `features/*` building blocks worth reusing

`SkillPicker` / `SkillTagInput` (async autocomplete against `GET /skills?q=`, optional "create by name") ·
`JobCard` / `JobResults` / `JobBadges` / `CompanyLogo` · `MatchExplanation` · `NotificationItem` · `useJobLifecycle`.

```tsx
<SkillTagInput value={skills} onChange={setSkills} allowCreate />        // chips + picker
<SkillPicker selected={rows} onAdd={append} onRemove={removeByName} />   // add-only picker (job form)
<JobResults query={useJobSearch(filters)} onPageChange={…} empty={<NoResults … />} />
const { request, dialog } = useJobLifecycle()   // request(job, 'publish' | 'pause' | 'resume' | 'close' | 'archive' | 'delete'); render {dialog}
```

---

## 12. Accessibility & performance checklist

Before opening a PR: one `<h1>` (`PageHeader`); every control labelled (`Field`/`aria-label`); errors in `role="alert"`;
loading regions `role="status"`/`aria-busy`; dialogs via Radix (focus trap + return); icons `aria-hidden` unless they
carry meaning; no colour-only meaning; keyboard path for every action (row menus use `DropdownMenu`; clickable cards use a
stretched link, not `onClick` on a `div`); test at 360 px (no horizontal page scroll — tables scroll inside their
container or switch to cards).

Performance: route-level code splitting (`lazyPage`); heavy libs behind `React.lazy` (Recharts is only loaded for staff
job pages); debounce inputs that drive requests; keep `staleTime` sensible; avoid request waterfalls; prefer
`select`/`placeholderData` over refetching.

---

## 13. Visual QA and the real-stack smoke test

Both scripts expect `npm run dev` (port 5173) and the API on :8000.

- `node scripts/screenshots.mjs [--only=home,jobs,cand,rec,dark,login,register] [--widths=1440,1024,768,390]` writes
  `frontend/screenshots/*.png` (git-ignored), logs console errors and **fails loudly on horizontal page overflow** at any
  width. Screenshots cover home, search (results/empty/error/filtered), job detail (visitor/candidate/staff), apply
  dialog, filter sheet, notifications + bell, settings, login/register (+ validation), manage list, job form
  (+ publish errors), row menu, and dark mode.
- `node scripts/e2e-smoke.mjs` drives the real API through the UI: filters/URL sync, skill autocomplete, match card,
  save/unsave, apply-dialog focus return, reload session restore, sign-out, recruiter create → edit → staff view →
  delete (net-zero data), HM/admin views. The login endpoint is rate limited (429 + `Retry-After`); wait a minute if the
  scripts are re-run in quick succession.

---

## 14. Backend notes the frontend relies on

- Pagination envelope `{items,page,page_size,total,pages}`; error envelope `{error:{code,message,details,request_id}}`.
- `GET /jobs/{id}` returns `JobDetail` (has `allowed_transitions`) for the owning company's staff/admin and `JobPublic`
  otherwise; the UI discriminates with `isStaffView()`.
- Salary/experience decimals are strings in responses.
- Job list items carry only skill **names**, so URL filters carry skill names too (`?skill=Python`), which the search
  endpoint resolves (names and aliases).
- Demo login shortcuts: shown from `GET /meta` when `demo_mode` is true (`demo_accounts`, `demo_password`); if `/meta` is
  absent (404) they appear only when `VITE_SHOW_DEMO_ACCOUNTS=true` (build-time; `.env.development` sets it for `npm run dev`).
- `GET /resumes` was not in the OpenAPI schema when wave 1 was built; `useMyResumes` accepts a bare array or a page
  envelope and treats 404/405 as "no résumés".
- Rotating, single-use refresh tokens: a second request with an already-rotated token revokes the session family. The
  client therefore uses a single-flight refresh, Web Locks across tabs and `keepalive`.
