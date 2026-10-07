/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base path (default "/api/v1"; same-origin via proxy). */
  readonly VITE_API_BASE_URL?: string
  /** "true" => show one-click demo accounts on /login when GET /meta is unavailable. */
  readonly VITE_SHOW_DEMO_ACCOUNTS?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
