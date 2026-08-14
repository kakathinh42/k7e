/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  /** 'dev' (default) | 'password' — see src/auth/config.ts. */
  readonly VITE_AUTH_MODE?: string
  /** Must mirror the API's jwt_identity_claim. Default 'sub'. */
  readonly VITE_IDENTITY_CLAIM?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
