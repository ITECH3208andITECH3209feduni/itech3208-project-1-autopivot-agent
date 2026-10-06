// Thin wrapper over fetch for the AutoPivot API.
//
// Requests go to same-origin paths; Vite proxies /auth and /api to FastAPI in
// development, and in production both are served from one host.

const TOKEN_KEY = 'autopivot.token'

export type DealershipActivity = {
  dealership_id: number
  active_users: number
  vehicle_count: number
  original_image_count: number
  job_count: number
  jobs_by_status: Record<string, number>
  latest_job_at: string | null
}

export type PlatformJobMetadata = {
  id: number
  vehicle_listing_id: number
  processing_type: string
  status: string
  review_state: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export type PlatformJobs = {
  items: PlatformJobMetadata[]
  total: number
  limit: number
  offset: number
}

export type Dealership = {
  id: number
  name: string
  location: string | null
  contact_name: string | null
  contact_email: string | null
  contact_phone: string | null
  status: string
  user_count: number
}

export type DealershipOnboardRequest = {
  name: string
  location: string
  contact_name: string
  contact_email: string
  contact_phone: string
  admin_email: string
  admin_first_name: string
  admin_last_name: string
}

export type DealershipProvisioned = {
  dealership: Dealership
  administrator: User
  initial_password: string
}

export type DealershipUser = Omit<User, 'dealership'>

export type DealershipUserCreate = {
  email: string
  first_name: string
  last_name: string
  role: 'dealership_admin' | 'dealership_staff'
}

export type DealershipUserProvisioned = {
  user: DealershipUser
  initial_password: string
}

export type User = {
  id: number
  email: string
  first_name: string
  last_name: string
  role: 'platform_admin' | 'dealership_admin' | 'dealership_staff'
  is_active: boolean
  must_change_password: boolean
  dealership: Dealership | null
}

export type LoginResponse = {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export type NavCounts = {
  vehicles: number
  backdrops: number
  needs_review: number
}

export type DashboardStats = {
  vehicles_this_month: number
  images_processed: number
  needs_review: number
}

export type ProcessingStatus = 'pending' | 'processing' | 'complete' | 'needs_review'

export type VehicleListing = {
  id: number
  stock_number: string | null
  title: string
  make: string
  model: string
  year: number
  variant: string | null
  price: string | null
  status: string
  processing_status: ProcessingStatus
  image_count: number
  created_at: string
  updated_at: string
}

/** What a photograph is of. Null until the classifier has seen it. */
export type ImageKind = 'exterior' | 'interior' | 'detail' | 'advertisement' | 'unknown'

export type ListingImage = {
  id: number
  image_type: 'original' | 'processed' | 'background' | 'plate_overlay'
  image_kind: ImageKind | null
  kind_confidence: number | null
  original_filename: string
  image_url: string
  width: number
  height: number
  file_size_bytes: number
  created_at: string
}

export type VehicleListingDetail = VehicleListing & {
  description: string | null
  images: ListingImage[]
}

export type UrlImportResult = {
  images: ListingImage[]
  /** Set when the import worked but the result deserves a second look. */
  note: string | null
}

export type VehicleListingCreate = {
  make: string
  model: string
  year: number
  variant?: string | null
  stock_number?: string | null
  price?: number | null
}

export type ProcessingJob = {
  id: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  processing_type: string
  input_image_id: number
  output_image_id: number | null
  output_image_url: string | null
  backdrop_id: number | null
  detected_angle: string | null
  angle_confidence: string | null
  plates_detected: number | null
  plate_treatment: string | null
  review_state: 'ok' | 'needs_review' | null
  model_used: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export type ProcessingSummary = {
  listing_id: number
  processing_status: ProcessingStatus
  total: number
  completed: number
  failed: number
  needs_review: number
  jobs: ProcessingJob[]
}

export type Backdrop = {
  id: number
  name: string
  /** Empty means the backdrop suits all angles. */
  suits_angles: string[]
  is_default: boolean
  image_url: string
  created_at: string
}

/** An API error carrying the status code, so callers can treat 401 specially. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

const sessionEndedListeners = new Set<() => void>()

/**
 * Called when the server refuses the stored token: it expired, an
 * administrator reset or deactivated the account, the password was changed
 * elsewhere, or the API restarted with a new signing key. The token has
 * already been dropped by then. Returns the unsubscribe.
 */
export function onSessionEnded(listener: () => void): () => void {
  sessionEndedListeners.add(listener)
  return () => { sessionEndedListeners.delete(listener) }
}

/**
 * The server refused `token`. Only if it is still the stored one is it dropped
 * and the end announced: a screen's burst of requests, all refused together,
 * ends the session once, and a straggler refused after the user has signed in
 * again, here or in another tab, leaves the new session alone.
 */
function refused(token: string) {
  if (tokenStore.get() !== token) return
  tokenStore.clear()
  for (const listener of [...sessionEndedListeners]) listener()
}

/**
 * Called when another tab stores, replaces or removes the token — a sign-in,
 * a password change or a sign-out there — with the token now stored. Tabs
 * share localStorage but are not told of each other's writes otherwise.
 * Returns the unsubscribe.
 */
export function onTokenChangedElsewhere(listener: (token: string | null) => void): () => void {
  function handle(event: StorageEvent) {
    // A null key is another tab clearing the whole of localStorage.
    if (event.key === TOKEN_KEY || event.key === null) listener(tokenStore.get())
  }
  window.addEventListener('storage', handle)
  return () => window.removeEventListener('storage', handle)
}

type RequestOptions = {
  /**
   * Send no token. Signing in has no use for one, and a stale token riding
   * along would turn a mistyped password into a "session ended".
   */
  anonymous?: boolean
}

async function request<T>(
  path: string, init: RequestInit = {}, { anonymous = false }: RequestOptions = {},
): Promise<T> {
  const token = anonymous ? null : tokenStore.get()
  const headers = new Headers(init.headers)
  // FormData must set its own Content-Type, because the multipart boundary is
  // generated by the browser and cannot be written by hand.
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(path, { ...init, headers })
  } catch {
    // fetch only rejects on network failure, never on a 4xx or 5xx.
    throw new ApiError(0, 'Could not reach the server. Is the API running?')
  }

  if (response.status === 204) return undefined as T

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    // A 401 on a request that carried a token is the server refusing the
    // session, whatever the endpoint; every other status leaves it alone.
    if (response.status === 401 && token) refused(token)

    // FastAPI puts a string in `detail` for our raised errors, and an array of
    // validation objects for 422s. Neither is safe to render directly.
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('. ')
          : `Request failed (${response.status}).`
    throw new ApiError(response.status, message)
  }

  return body as T
}

export const api = {
  login: (email: string, password: string) =>
    request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }, { anonymous: true }),

  me: () => request<User>('/auth/me'),

  /**
   * Answers as login does. The change revokes every token issued before it,
   * the one it was sent with included, so the caller must store the new one.
   */
  changePassword: (current_password: string, new_password: string) =>
    request<LoginResponse>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

  platformDealerships: () =>
    request<Dealership[]>('/api/platform/dealerships'),

  platformActivity: (id: number) =>
    request<DealershipActivity>(`/api/platform/dealerships/${id}/activity`),

  platformJobs: (id: number, offset = 0, status = '') => {
    const query = new URLSearchParams({ limit: '20', offset: String(offset) })
    if (status) query.set('status', status)
    return request<PlatformJobs>(`/api/platform/dealerships/${id}/jobs?${query}`)
  },

  onboardDealership: (payload: DealershipOnboardRequest) =>
    request<DealershipProvisioned>('/api/platform/dealerships', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  dealershipUsers: () => request<DealershipUser[]>('/api/dealership/users'),

  addDealershipUser: (payload: DealershipUserCreate) =>
    request<DealershipUserProvisioned>('/api/dealership/users', {
      method: 'POST', body: JSON.stringify(payload),
    }),

  resetDealershipUser: (userId: number) =>
    request<{ initial_password: string }>(`/api/dealership/users/${userId}/reset-password`, { method: 'POST' }),

  deactivateDealershipUser: (userId: number) =>
    request<DealershipUser>(`/api/dealership/users/${userId}/deactivate`, { method: 'POST' }),

  // The platform-administrator equivalents of the four above — same shapes,
  // scoped by an explicit dealership id in the path instead of the caller's
  // own, since a platform administrator belongs to no dealership at all.
  platformDealershipUsers: (dealershipId: number) =>
    request<DealershipUser[]>(`/api/platform/dealerships/${dealershipId}/users`),

  addPlatformDealershipUser: (dealershipId: number, payload: DealershipUserCreate) =>
    request<DealershipUserProvisioned>(`/api/platform/dealerships/${dealershipId}/users`, {
      method: 'POST', body: JSON.stringify(payload),
    }),

  resetPlatformDealershipUser: (dealershipId: number, userId: number) =>
    request<{ initial_password: string }>(
      `/api/platform/dealerships/${dealershipId}/users/${userId}/reset-password`, { method: 'POST' },
    ),

  deactivatePlatformDealershipUser: (dealershipId: number, userId: number) =>
    request<DealershipUser>(
      `/api/platform/dealerships/${dealershipId}/users/${userId}/deactivate`, { method: 'POST' },
    ),

  dashboardStats: () => request<DashboardStats>('/api/dashboard/stats'),

  navCounts: () => request<NavCounts>('/api/dashboard/counts'),

  listing: (id: number) => request<VehicleListingDetail>(`/api/listings/${id}`),

  createListing: (payload: VehicleListingCreate) =>
    request<VehicleListingDetail>('/api/listings', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteListing: (id: number) =>
    request<void>(`/api/listings/${id}`, { method: 'DELETE' }),

  uploadImages: (listingId: number, files: File[]) => {
    const body = new FormData()
    // The field repeats once per file: FastAPI collects them into list[UploadFile].
    for (const file of files) body.append('files', file)
    return request<ListingImage[]>(`/api/listings/${listingId}/images`, {
      method: 'POST',
      body,
    })
  },

  importImagesFromUrl: (listingId: number, url: string) =>
    request<UrlImportResult>(`/api/listings/${listingId}/images/from-url`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  deleteImage: (listingId: number, imageId: number) =>
    request<void>(`/api/listings/${listingId}/images/${imageId}`, { method: 'DELETE' }),

  processListing: (listingId: number, backdropId: number | null) =>
    request<ProcessingSummary>(`/api/listings/${listingId}/process`, {
      method: 'POST',
      body: JSON.stringify({ backdrop_id: backdropId }),
    }),

  listingJobs: (listingId: number) =>
    request<ProcessingSummary>(`/api/listings/${listingId}/jobs`),

  backdrops: () => request<Backdrop[]>('/api/backdrops'),

  createBackdrop: (name: string, file: File, suitsAngles: string[] = []) => {
    const body = new FormData()
    body.append('name', name)
    body.append('file', file)
    body.append('suits_angles', suitsAngles.join(','))
    return request<Backdrop>('/api/backdrops', { method: 'POST', body })
  },

  deleteBackdrop: (id: number) =>
    request<void>(`/api/backdrops/${id}`, { method: 'DELETE' }),

  /** Stored files are behind auth, so they cannot be used as a plain <img src>. */
  fetchFile: async (url: string): Promise<string> => {
    const token = tokenStore.get()
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token ?? ''}` },
    })
    if (response.status === 401 && token) refused(token)
    if (!response.ok) throw new ApiError(response.status, 'Image unavailable.')
    return URL.createObjectURL(await response.blob())
  },

  listings: (
    params: { limit?: number; processing_status?: ProcessingStatus; q?: string } = {},
  ) => {
    const query = new URLSearchParams()
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    if (params.processing_status) query.set('processing_status', params.processing_status)
    if (params.q) query.set('q', params.q)
    const suffix = query.toString() ? `?${query}` : ''
    return request<VehicleListing[]>(`/api/listings${suffix}`)
  },
}
