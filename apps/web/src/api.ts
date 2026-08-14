/**
 * api.ts — Typed API client for k7e.
 *
 * Identity depends on the auth mode (see auth/config.ts): `dev` sends the
 * header seam (`X-User-Id: dev`); `password` sends the Bearer JWT from
 * the token store instead.  In development the Vite dev-server proxies
 * `/api/*` to the FastAPI backend, stripping the `/api` prefix before
 * forwarding (see vite.config.ts).  In production the `VITE_API_BASE` env
 * variable should point at the API origin (e.g. `https://api.example.com/api`).
 */

import { authMode } from './auth/config'
import { getToken, notifyUnauthorized } from './auth/tokenStore'

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * Non-2xx response. The message keeps the legacy `HTTP <status>: <text>`
 * shape (retry predicates match on it, e.g. TeamDetailPage's 404 check);
 * `status` is the structured accessor new code should prefer.
 */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, statusText: string) {
    super(`HTTP ${status}: ${statusText}`)
    this.name = 'ApiError'
    this.status = status
  }
}

// ---------------------------------------------------------------------------
// TypeScript types mirroring backend Pydantic schemas
// ---------------------------------------------------------------------------

/** Response body returned by POST /ingest/upload (mirrors UploadResponse). */
export interface UploadResponse {
  workflow_id: string
  raw_document_id: string
}

/** Which space a page lives in (mirrors SpaceRef). */
export interface SpaceRef {
  slug: string
  name: string
  kind: 'personal' | 'team' | 'public'
}

/** Compact summary of a published knowledge item (mirrors ItemSummary). */
export interface ItemSummary {
  id: string
  slug: string
  title: string
  status: string
  type: string
  domain: string | null
  tags: string[]
  updated_at: string
  space?: SpaceRef | null
}

/** One resolved provenance entry (mirrors a dict in ItemDetail.sources). */
export interface SourceRef {
  kind: 'document' | 'page'
  label?: string
  source_system?: string | null
  raw_document_id?: string | null
  slug?: string
  title?: string
}

/** Full detail of a published knowledge item (mirrors ItemDetail). */
export interface ItemDetail extends ItemSummary {
  markdown_body: string
  version: number
  citations: unknown[]
  model_id: string
  sources: SourceRef[]
}

/** Per-hit ranking explanation (admin explain mode). Mirrors ScoreBreakdown. */
export interface ScoreBreakdown {
  total: number
  keyword?: number | null
  vector?: number | null
  recency?: number | null
  importance?: number | null
  weights?: Record<string, number> | null
  expanded: boolean
  via?: string | null
  edge_score?: number | null
  parent_score?: number | null
  decay?: number | null
}

/** A single result from a search query (mirrors SearchHit). */
export interface SearchHit {
  id: string
  slug: string
  title: string
  snippet: string
  score: number
  breakdown?: ScoreBreakdown | null
}

/** Response body for GET /search (mirrors SearchResponse). */
export interface SearchResponse {
  hits: SearchHit[]
}

/** One facet value + its count (mirrors FacetCount). */
export interface FacetCount {
  value: string
  count: number
}

/** Available classification facets with counts (mirrors FacetsResponse). */
export interface Facets {
  domains: FacetCount[]
  tags: FacetCount[]
  types: FacetCount[]
}

/** A graph node — a published page (mirrors GraphNode). */
export interface GraphNode {
  id: string
  slug: string
  title: string
  degree: number
}

/** An undirected related edge (mirrors GraphEdge). */
export interface GraphEdge {
  source: string
  target: string
  score: number
  relation: string
  origin: string
}

/** Response body for GET /graph (mirrors GraphResponse). */
export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ---------------------------------------------------------------------------
// Core request helper
// ---------------------------------------------------------------------------

/**
 * Perform an HTTP request, attaching identity per the auth mode.
 *
 * - `dev` mode: the dev header seam (`X-User-Id`/`X-User-Roles`), unchanged.
 * - `password`: `Authorization: Bearer <JWT>` and no `X-User-*` headers
 *   (the API ignores them when JWT auth is on; not sending them keeps the
 *   contract honest). A 401 fires the debounced unauthorized signal so the
 *   AuthProvider can re-enter login.
 * - For JSON requests (`body` is a plain object): sets `Content-Type:
 *   application/json` and serializes the body.
 * - For `FormData` bodies: omits `Content-Type` so the browser can set the
 *   correct `multipart/form-data` boundary automatically.
 * - Throws an `ApiError` (message `HTTP <status>: <text>`) on any non-2xx.
 */
async function request<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  const mode = authMode()

  if (mode === 'dev') {
    // Dev identity headers required by the backend auth seam (env=dev).
    headers.set('X-User-Id', 'dev')
    headers.set('X-User-Roles', 'reviewer')
  } else {
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }

  // Set Content-Type for JSON bodies; leave it unset for FormData so the
  // browser includes the multipart boundary automatically.
  if (
    init.body !== undefined &&
    !(init.body instanceof FormData)
  ) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, { ...init, headers })

  if (!response.ok) {
    if (response.status === 401 && mode !== 'dev') {
      notifyUnauthorized()
    }
    throw new ApiError(response.status, response.statusText)
  }

  // Handle 204 No Content — return void-equivalent (defensive; most endpoints return 200).
  if (response.status === 204) {
    return undefined as unknown as T
  }

  return response.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Exported API functions
// ---------------------------------------------------------------------------

/**
 * Upload a document file for ingestion.
 *
 * POST /ingest/upload  (multipart/form-data, field name "file")
 */
export async function uploadDocument(
  file: File,
  opts: { sourceTier?: string; sourceSystem?: string; space?: string } = {},
): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  if (opts.sourceSystem) form.append('source_system', opts.sourceSystem)
  if (opts.sourceTier) form.append('source_tier', opts.sourceTier)
  if (opts.space) form.append('space', opts.space)
  return request<UploadResponse>(`${API_BASE}/ingest/upload`, {
    method: 'POST',
    body: form,
  })
}

/** Status of an in-progress or completed ingest job (mirrors IngestStatusOut). */
export interface IngestStatus {
  raw_document_id: string
  status: string       // received | processing | done | failed
  workflow_id: string | null
}

/**
 * Fetch the current status of an ingest job by raw_document_id.
 * Used to re-attach progress tracking after a page refresh.
 *
 * GET /ingest/status/{raw_document_id}
 */
export async function getIngestStatus(rawDocumentId: string): Promise<IngestStatus> {
  return request<IngestStatus>(`${API_BASE}/ingest/status/${encodeURIComponent(rawDocumentId)}`)
}

/**
 * List published knowledge items, optionally narrowed by classification.
 *
 * GET /items?type=&domain=&tag=&tag=
 */
export async function listItems(
  params: { type?: string; domain?: string; tags?: string[]; space?: string } = {},
): Promise<ItemSummary[]> {
  const qs = new URLSearchParams()
  if (params.type) qs.set('type', params.type)
  if (params.domain) qs.set('domain', params.domain)
  if (params.space) qs.set('space', params.space)
  for (const tag of params.tags ?? []) qs.append('tag', tag)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<ItemSummary[]>(`${API_BASE}/items${suffix}`)
}

/** A space the caller can read (mirrors SpaceSummary). */
export interface Space {
  slug: string
  name: string
  kind: 'personal' | 'team' | 'public'
  item_count: number
}

/** List the caller's accessible spaces with kinds + counts. GET /spaces */
export async function listSpaces(): Promise<Space[]> {
  return request<Space[]>(`${API_BASE}/spaces`)
}

/**
 * Fetch the full detail of a single knowledge item by its slug.
 *
 * GET /items/{slug}
 */
export async function getItem(slug: string): Promise<ItemDetail> {
  return request<ItemDetail>(`${API_BASE}/items/${encodeURIComponent(slug)}`)
}

/**
 * Search knowledge items by a text query, optionally narrowed by classification.
 *
 * GET /search?q={q}&domain=&tag=
 */
export async function search(
  q: string,
  params: { domain?: string; tags?: string[]; explain?: boolean; space?: string } = {},
): Promise<SearchResponse> {
  const qs = new URLSearchParams({ q })
  if (params.domain) qs.set('domain', params.domain)
  for (const tag of params.tags ?? []) qs.append('tag', tag)
  if (params.explain) qs.set('explain', 'true')
  if (params.space) qs.set('space', params.space)
  return request<SearchResponse>(`${API_BASE}/search?${qs.toString()}`)
}

/**
 * Fetch the available classification facets (domains/tags/types + counts).
 *
 * GET /facets
 */
export async function getFacets(): Promise<Facets> {
  return request<Facets>(`${API_BASE}/facets`)
}

/**
 * Fetch the page-to-page knowledge graph (nodes + related edges).
 *
 * GET /graph?min_score={minScore}
 */
export async function getGraph(minScore = 0, space?: string): Promise<GraphResponse> {
  const qs = new URLSearchParams({ min_score: String(minScore) })
  if (space) qs.set('space', space)
  return request<GraphResponse>(`${API_BASE}/graph?${qs.toString()}`)
}

/** One upload's compile cost (mirrors IngestRunOut). */
export interface IngestRun {
  id: string
  raw_document_id: string | null
  filename: string
  source_slug: string | null
  model_id: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  llm_calls: number
  cost_usd: number
  page_count: number
  created_at: string
  /** Which space the upload landed in (private/team/public), or null if unknown. */
  space?: SpaceRef | null
}

/**
 * Upload history: recent ingests with token usage + estimated $ cost.
 *
 * GET /ingest/history
 */
export async function getIngestHistory(limit = 50): Promise<IngestRun[]> {
  return request<IngestRun[]>(
    `${API_BASE}/ingest/history?limit=${encodeURIComponent(limit)}`,
  )
}

/** Corpus-wide embedding progress (mirrors EmbeddingStatusOut). */
export interface EmbeddingStatus {
  total: number
  embedded: number
  pending: number
}

/**
 * Embedding progress across the chunk index — embedded vs. still pending.
 * Optionally scoped to the History filters (space kind + month/year) so the
 * card mirrors the filtered table.
 *
 * GET /ingest/embedding-status
 */
export async function getEmbeddingStatus(
  params: { spaceKind?: 'personal' | 'team' | 'public'; year?: number; month?: number } = {},
): Promise<EmbeddingStatus> {
  const qs = new URLSearchParams()
  if (params.spaceKind) qs.set('space_kind', params.spaceKind)
  if (params.year !== undefined) qs.set('year', String(params.year))
  if (params.month !== undefined) qs.set('month', String(params.month))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<EmbeddingStatus>(`${API_BASE}/ingest/embedding-status${suffix}`)
}

// ---------------------------------------------------------------------------
// Teams (M3)
// ---------------------------------------------------------------------------

/** A team member (mirrors backend MemberOut). */
export interface TeamMember {
  user_id: string
  role: string
  created_at: string
}

/** A team with its members (mirrors backend TeamOut). */
export interface Team {
  id: string
  slug: string
  name: string
  org_id: string
  space_id: string
  created_by: string
  created_at: string
  members: TeamMember[]
}

/** List teams the current user belongs to.  GET /teams */
export async function listTeams(): Promise<Team[]> {
  return request<Team[]>(`${API_BASE}/teams`)
}

/** Fetch one team + its members (members only).  GET /teams/{slug} */
export async function getTeam(slug: string): Promise<Team> {
  return request<Team>(`${API_BASE}/teams/${encodeURIComponent(slug)}`)
}

/** Create a team; the caller becomes owner.  POST /teams */
export async function createTeam(slug: string, name: string): Promise<Team> {
  return request<Team>(`${API_BASE}/teams`, {
    method: 'POST',
    body: JSON.stringify({ slug, name }),
  })
}

/** Add a member to a team.  POST /teams/{slug}/members */
export async function addMember(
  slug: string,
  userId: string,
  role: string,
): Promise<TeamMember> {
  return request<TeamMember>(`${API_BASE}/teams/${encodeURIComponent(slug)}/members`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, role }),
  })
}

/** Remove a member from a team.  DELETE /teams/{slug}/members/{userId} */
export async function removeMember(slug: string, userId: string): Promise<void> {
  await request<void>(
    `${API_BASE}/teams/${encodeURIComponent(slug)}/members/${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  )
}

// ---------------------------------------------------------------------------
// Personal Access Tokens
// ---------------------------------------------------------------------------

/** A PAT as listed (never carries the plaintext). */
export interface Pat {
  id: string
  name: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
}

/** The create response — the plaintext `token` is shown ONCE. */
export interface PatCreated {
  id: string
  name: string
  token: string
  expires_at: string | null
}

/** List the caller's PATs.  GET /pat */
export async function listPats(): Promise<Pat[]> {
  return request<Pat[]>(`${API_BASE}/pat`)
}

/** Create a PAT; the plaintext is returned once.  POST /pat */
export async function createPat(
  name: string,
  expiresDays?: number,
): Promise<PatCreated> {
  return request<PatCreated>(`${API_BASE}/pat`, {
    method: 'POST',
    body: JSON.stringify(
      expiresDays ? { name, expires_days: expiresDays } : { name },
    ),
  })
}

/** Revoke a PAT.  DELETE /pat/{id} */
export async function revokePat(id: string): Promise<void> {
  await request<void>(`${API_BASE}/pat/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}
