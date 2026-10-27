import { expireSession, getRefreshToken, getToken, getSessionGeneration, refreshAccessToken, type Role } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
let activeDatasetId: string | null = null
let datasetVersion = 0
const pendingGets = new Map<string, Promise<unknown>>()

export function getRequestContext(): string {
  return `${datasetVersion}|${getSessionGeneration()}|${localStorage.getItem('sem5_user')}`
}

export function setDatasetScope(id: string | null) {
  activeDatasetId = id
  datasetVersion += 1
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return { ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(activeDatasetId ? { 'X-Dataset-ID': activeDatasetId } : {}) }
}

function ensureContext(context: string, message = 'Dataset context changed; stale response discarded.') {
  if (context !== getRequestContext()) throw new Error(message)
}

async function requestResponse(path: string, init: RequestInit = {}, retry = true, context = getRequestContext()): Promise<Response> {
  const session = getSessionGeneration()
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init.headers as Record<string, string>), ...authHeaders() },
  })
  ensureContext(context)
  if (r.status === 401 && retry && getRefreshToken()) {
    const token = await refreshAccessToken()
    ensureContext(context)
    if (token) return requestResponse(path, init, false, context)
  }
  if (r.status === 401 && (!retry || !getRefreshToken())) {
    expireSession(session)
    throw new Error('Session expired. Sign in again. (Request failed: 401)')
  }
  if (!r.ok) {
    const error = await r.json().catch(() => null)
    ensureContext(context)
    throw new Error(typeof error?.detail === 'string' ? error.detail : `Request failed: ${r.status}`)
  }
  return r
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const context = getRequestContext()
  const r = await requestResponse(path, init, true, context)
  if (r.status === 204) { ensureContext(context); return undefined as T }
  const data = await r.json()
  ensureContext(context)
  return data as T
}

export interface DatasetColumn {
  name: string; dtype: string; role: string; confidence: number; missing: number; unique: number; constant: boolean; ambiguous_date: boolean
}
export interface Dataset {
  source_type?: string; bundle_id?: string; relative_path?: string; internal_name?: string; original_filename?: string
  tables?: Dataset[]; relational_analysis?: { supported: boolean; reason: string }
  updated_at: string | null
  dataset_id: string; dataset_name: string; status: string; row_count: number; column_count: number; error: string | null; read_only: boolean
  schema: { columns?: DatasetColumn[] }
  semantics: { fields?: Record<string, string>; currency_code?: string | null; domain?: string; ambiguities?: { role: string; candidates: string[] }[] }
  capabilities: Record<string, { available: boolean; reason: string | null }>
  quality: { missing_values?: number; duplicate_rows?: number; warnings?: string[] }
}
export interface UploadLimits { max_bytes: number; max_rows: number; max_columns: number; max_cells: number; max_files: number; max_seconds: number; max_expanded_bytes?: number; bundle_max_rows?: number; bundle_max_cells?: number; bundle_max_seconds?: number; max_table_rows?: number; max_table_cells?: number }
export interface ImportJob { job_id: string; status: string; stage: string; completed_tables: number; total_tables: number; stored_rows: number; current_file?: string; error?: string; result?: Dataset }
const pendingBundleKey = () => `sem5_pending_bundle:${localStorage.getItem('sem5_user')}`
export function cancelBundleImport() {
  const id = localStorage.getItem(pendingBundleKey())
  return id ? request<ImportJob>(`/api/datasets/bundles/jobs/${id}/cancel`, { method: 'POST' }) : Promise.resolve(null)
}
export async function resumeBundleImport(progress?: (job: ImportJob) => void): Promise<Dataset | null> {
  const key = pendingBundleKey(); const id = localStorage.getItem(key)
  if (!id) return null
  while (true) {
    const job = await request<ImportJob>(`/api/datasets/bundles/jobs/${id}`)
    progress?.(job)
    if (job.status === 'READY' && job.result) { localStorage.removeItem(key); return job.result }
    if (job.status === 'FAILED' || job.status === 'CANCELLED') { localStorage.removeItem(key); throw new Error(job.error || 'Import cancelled. Nothing was imported.') }
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
}
export function getUploadLimits() { return getJson<UploadLimits>('/api/datasets/upload-limits') }
export function getZipManifest(file: File) {
  const form = new FormData(); form.append('file', file)
  return request<{ files: { path: string; bytes: number }[]; total_bytes: number; ignored?: {path:string;reason:string}[] }>('/api/datasets/bundles/zip-preview', { method: 'POST', body: form })
}
export async function uploadDatasetBundle(files: File[], name: string, zip = false, progress?: (job: ImportJob) => void) {
  const form = new FormData(); form.append('name', name)
  for (const file of files) {
    form.append(zip ? 'file' : 'files', file)
    if (!zip) form.append('paths', file.webkitRelativePath || file.name)
  }
  const result = await request<Dataset | ImportJob>(zip ? '/api/datasets/bundles/zip' : '/api/datasets/bundles/upload', { method: 'POST', body: form })
  if ('job_id' in result) {
    localStorage.setItem(pendingBundleKey(), result.job_id)
    progress?.(result)
    const dataset = await resumeBundleImport(progress)
    if (!dataset) throw new Error('Import status was lost. Check Dataset Manager before retrying.')
    return dataset
  }
  return result
}
export function listDatasets() { return getJson<{ datasets: Dataset[]; active_dataset_id: string | null }>('/api/datasets') }
export function selectDataset(id: string) { return request<Dataset>(`/api/datasets/${id}/select`, { method: 'POST' }) }
export function deleteDataset(id: string) { return request<void>(`/api/datasets/${id}`, { method: 'DELETE' }) }
export function getDatasetPreview(id: string) { return getJson<{ columns: string[]; rows: Record<string, string | number | null>[] }>(`/api/datasets/${id}/preview`) }
export function uploadDataset(file: File, name: string) {
  const form = new FormData(); form.append('file', file); form.append('name', name)
  return request<Dataset>('/api/datasets/upload', { method: 'POST', body: form })
}
export function updateDatasetSchema(id: string, schema: { fields: Record<string, string | null>; currency_code: string | null; domain: string; date_order?: string }) {
  return request<Dataset>(`/api/datasets/${id}/schema`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(schema) })
}

function getJson<T>(path: string): Promise<T> {
  // Coalesce only concurrent identical reads (including Strict Mode effects).
  // Results are never cached after completion, and identity includes the user
  // and dataset generation so a switch cannot reuse an old response.
  const key = `${getRequestContext()}|${path}`
  const pending = pendingGets.get(key)
  if (pending) return pending as Promise<T>
  const result = request<T>(path).finally(() => pendingGets.delete(key))
  pendingGets.set(key, result)
  return result
}

export function health() {
  return getJson<{ status: string }>('/health')
}

export interface Kpis {
  filters: { date_from: string | null; date_to: string | null; order_status: string | null }
  kpis: {
    total_orders: number
    total_revenue: number
    total_freight: number
    avg_order_value: number
    unique_customers: number
    items_sold: number
    products_sold: number
    active_sellers: number
    avg_review_score: number | null
    avg_delivery_days: number | null
  }
}

export function getKpis(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<Kpis>(`/api/dashboard/kpis${qs ? `?${qs}` : ''}`)
}

export interface MonthlyPoint {
  period: string
  orders: number
  revenue: number
}

export function getMonthlyRevenue() {
  return getJson<{ series: MonthlyPoint[] }>('/api/dashboard/monthly-revenue')
}

export interface CategoryPoint {
  category: string
  revenue: number
  items: number
}

export function getRevenueByCategory() {
  return getJson<{ series: CategoryPoint[] }>('/api/dashboard/revenue-by-category')
}

export interface StatusPoint {
  status: string
  orders: number
}

export function getOrdersByStatus() {
  return getJson<{ series: StatusPoint[] }>('/api/dashboard/orders-by-status')
}

// ---- Analytics ----

export interface FilterOptions {
  dynamic?: { field: string; label: string; values: string[] }[]
  has_date?: boolean
  categories: string[]
  customer_states: string[]
  seller_states: string[]
  order_statuses: string[]
  payment_types: string[]
  review_scores: number[]
  date_range: { min: string; max: string }
}

export function getFilterOptions() {
  return getJson<FilterOptions>('/api/analytics/filters')
}

export function getAnalyticsOverview(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/overview${qs ? `?${qs}` : ''}`)
}

export function getAnalyticsSales(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/sales${qs ? `?${qs}` : ''}`)
}

export function getAnalyticsOrders(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/orders${qs ? `?${qs}` : ''}`)
}

export function getAnalyticsCustomers(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/customers${qs ? `?${qs}` : ''}`)
}

export function getAnalyticsProducts(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/products${qs ? `?${qs}` : ''}`)
}

export function getAnalyticsSellers(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/sellers${qs ? `?${qs}` : ''}`)
}

export function getAnalyticsDelivery(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  return getJson<any>(`/api/analytics/delivery${qs ? `?${qs}` : ''}`)
}

// ---- ML ----

function modelParams(params: Record<string, string>) {
  // Chart grain controls analytics presentation, not trained daily/entity inputs.
  // Preserve dataset/date/dimension filters; ML endpoints reject non-daily grains.
  const selected = { ...params }
  delete selected.grain
  return selected
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export interface MlModel {
  runtime_ready?: boolean; runtime_reason?: string; version?: string
  compatibility?: { compatible: boolean; reasons: string[]; training_domain: string | null }
  metrics_scope?: string
  name: string
  algorithm: string | null
  trained_at: string | null
  metrics: Record<string, unknown> | null
  artifact_available: boolean
}

export interface MlFeature {
  name: string
  status: string
  models: MlModel[]
}

export function getMlStatus(params: Record<string, string> = {}) {
  return getJson<{ features: MlFeature[]; source_candidates?: MlFeature[] }>(`/api/ml/status?${new URLSearchParams(modelParams(params))}`)
}

export function getModelDetail(name: string, params: Record<string, string> = {}) {
  return getJson<any>(`/api/ml/models/${encodeURIComponent(name)}?${new URLSearchParams(modelParams(params))}`)
}

export interface ForecastPoint {
  date: string
  orders?: number | null
  revenue?: number | null
}

export interface ForecastResponse {
  history_tail: ForecastPoint[]; forecast: ForecastPoint[]; historical_series?: ForecastPoint[]; forecast_series?: ForecastPoint[]
  historical_coverage?: {from:string;to:string;calendar_positions:number;recorded_days:number;missing_dates:number;unknown_target_days:number;missing_target_positions:number;zero_filled:number} | null
  status?: string; reason?: string; model?: {name?:string;version?:string;algorithm?:string}; warnings?:string[]
  synthetic?:boolean; unit?:string; forecast_origin?:string; data_coverage?:{from:string;to:string;observed_days:number}
  synthetic_registration?:{status:string;datasets:{dataset_id:string;dataset_name:string;table:string}[]}
  selected_scope?:{dataset_id:string;dataset_name:string}
}

export interface BusinessEvidenceResponse {
  status: string; source: string; currency_code?: string | null; measurement_window?: string
  cards: { label: string; value: number | null }[]
  series: { period: string; first_time?: number; returning?: number; revenue?: number }[]
  frequency?: { orders: number; customers: number }[]
  rankings: { label: string; value: number; orders?: number; late?: number; mean_late_days?: number | null }[]
  recommendations: { id: string; title: string; priority: string; observation: string; suggested_action: string; measurement_window: string; limitations: string; metric_source: string; evidence: Record<string, unknown> }[]
  limitations: string[]
}

export function getBusinessEvidence(domain: 'revenue' | 'customers' | 'sellers', params: Record<string, string> = {}) {
  return getJson<BusinessEvidenceResponse>(`/api/analytics/business?${new URLSearchParams({ ...params, domain })}`)
}

export function getForecast(periods = 30, target: 'orders' | 'revenue' = 'orders', params: Record<string, string> = {}) {
  return getJson<ForecastResponse>(
    `/api/ml/forecast?${new URLSearchParams({ ...modelParams(params), periods: String(periods), target })}`,
  )
}

export interface SeasonalDemoResponse {
  target: 'orders' | 'revenue'; horizon: number; artifact_horizon: number; training_cutoff: string
  model: { name: string; algorithm: string; version: string }
  forecast: { date: string; orders?: number; revenue?: number }[]
  history: { date: string; actual: number; data_source: string }[]
  validation_metrics: Record<string, string | number | boolean | null> | null
  benchmark_metrics: Record<string, string | number | boolean | null> | null
  provenance: { working_series: boolean; synthetic_backcast_and_extension_included: boolean; generated_days_in_final_benchmark_pct: number; note: string }
  warnings: string[]
}

export function getSeasonalDemoForecast(target: 'orders' | 'revenue', horizon: 30 | 90 | 365) {
  return getJson<SeasonalDemoResponse>(`/api/ml/seasonal-demo?${new URLSearchParams({ target, horizon: String(horizon) })}`)
}

export interface OfflineEvaluationPoint {
  date: string
  actual: number
  prediction: number
  data_origin: 'source_observed' | 'synthetic_extension'
  peak_threshold?: number
  dip_threshold?: number
  prediction_peak?: number | null
  prediction_dip?: number | null
}

export interface OfflineEvaluationResult {
  target: 'orders' | 'revenue' | 'profit'
  horizon: 30 | 90
  model: string
  available: boolean
  reason?: string
  quality_status: 'validation_only'
  semantic_status?: string
  target_definition?: string
  unit?: string
  evaluation_period?: { from: string; to: string }
  points?: OfflineEvaluationPoint[]
  metrics?: { mae: number; rmse: number; r2: number | null }
  peak_metrics?: { precision: number | null; recall: number | null; magnitude_mae: number | null; normal_period_mae: number | null; timing_mae_days: number | null }
  peak_definition?: string
  origin_count?: number
  provenance?: { source_observed_points: number; synthetic_extension_points: number }
  warnings?: string[]
}

export interface OfflineEvaluationResponse {
  status: 'available' | 'unavailable'
  label: string
  experiment: string
  validation_protocol: string
  results: OfflineEvaluationResult[]
}

export function getOfflineModelEvaluation() {
  return getJson<OfflineEvaluationResponse>('/api/ml/offline-evaluation')
}

export interface MlCompatibility {
  compatible: boolean
  reasons: string[]
  contract: Record<string, unknown>
  training_domain: string | null
  dataset_id: string
  artifact_available: boolean
}

export interface MlNotApplicable {
  status: 'not_applicable'
  reason: string
  compatibility: MlCompatibility
  dataset_id: string
}

export type CustomerSegmentsResponse = MlNotApplicable | {
  status: 'available'
  segments: Array<{ segment: number; customers: number; monetary: number }>
  compatibility: MlCompatibility
  dataset_id: string
}

export function getCustomerSegments(params: Record<string, string> = {}) {
  return getJson<CustomerSegmentsResponse>(`/api/ml/segments/customers?${new URLSearchParams(modelParams(params))}`)
}

export type AnomaliesResponse = MlNotApplicable | {
  status: 'available'
  n_days: number
  n_anomalies: number
  anomalies: Array<{ date: string; orders: number; revenue: number; anomaly: number; score: number; customers?: number; rows?: number }>
  compatibility: MlCompatibility
  dataset_id: string
}

export function getAnomalies(params: Record<string, string> = {}) {
  return getJson<AnomaliesResponse>(`/api/ml/anomalies?${new URLSearchParams(modelParams(params))}`)
}

export interface SalesPredictInput {
  purchase_month: number
  purchase_weekday: number
  purchase_hour: number
  n_items: number
  customer_state: string
  product_category_name: string
}

export type SalesPredictionResponse = MlNotApplicable | {
  status: 'available'; predicted_item_revenue: number; currency: string; dataset_id: string
}
export function predictSales(input: SalesPredictInput, params: Record<string, string> = {}) {
  return postJson<SalesPredictionResponse>(
    `/api/ml/predict/sales?${new URLSearchParams(modelParams(params))}`,
    input,
  )
}

export interface ProductSegment {
  segment: number
  products: number
  revenue: number
  quantity: number
  avg_price: number
  revenue_share: number
  quantity_share: number
}

export interface TopProduct {
  product: string
  category: string
  segment: number
  revenue: number
  quantity: number
  avg_price: number
}

export interface ProductSegmentationResponse {
  status?: string
  reason?: string
  segments: ProductSegment[]
  top_products: TopProduct[]
  k: number
}

export function getProductSegments(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(modelParams(params)).toString()
  return getJson<ProductSegmentationResponse>(
    `/api/ml/product-segmentation${qs ? `?${qs}` : ''}`
  )
}

// ---- AI Insights ----

export interface InsightsResponse {
  answer: string
  sources: string[]
  status: string
  provider: string | null
  role: string
}

export function queryInsights(question: string, context_limit = 20, params: Record<string, string> = {}) {
  return postJson<InsightsResponse>(`/api/insights/query?${new URLSearchParams(params)}`, { question, context_limit })
}

// ---- Reports ----

export async function downloadBusinessReport(params: Record<string, string> = {}) {
  const context = getRequestContext()
  const response = await requestResponse(`/api/reports/business-sales.docx?${new URLSearchParams(params)}`, {}, true, context)
  if (!response.headers.get('Content-Type')?.includes('application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
    throw new Error('The server did not return a Word document. Retry the report.')
  }
  const blob = await response.blob()
  ensureContext(context, 'Dataset or session changed; report discarded.')
  const prefix = blob.slice(0, 4)
  // Older browser shims (including jsdom's Blob) expose FileReader but omit
  // Blob.arrayBuffer(). Keep the DOCX magic-byte validation on both paths.
  const bytes = typeof prefix.arrayBuffer === 'function'
    ? await prefix.arrayBuffer()
    : await new Promise<ArrayBuffer>((resolve, reject) => {
        const reader = new FileReader()
        reader.onerror = () => reject(reader.error || new Error('Could not inspect the Word document package.'))
        reader.onload = () => reader.result instanceof ArrayBuffer
          ? resolve(reader.result)
          : reject(new Error('Could not inspect the Word document package.'))
        reader.readAsArrayBuffer(prefix)
      })
  const signature = new Uint8Array(bytes)
  ensureContext(context, 'Dataset or session changed; report discarded.')
  if (signature.length !== 4 || signature[0] !== 80 || signature[1] !== 75 || signature[2] !== 3 || signature[3] !== 4) {
    throw new Error('The returned document package is invalid. Retry the report.')
  }
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = 'business-sales-analysis.docx'
  document.body.appendChild(link); link.click(); link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  return { filename: 'business-sales-analysis.docx', bytes: blob.size, generatedAt: new Date().toISOString() }
}

export async function downloadReport(report: string, params: Record<string, string> = {}) {
  const context = getRequestContext()
  const qs = new URLSearchParams({ ...params, report }).toString()
  const r = await requestResponse(`/api/reports/export?${qs}`, {}, true, context)
  const blob = await r.blob()
  ensureContext(context, 'Dataset or session changed; export discarded.')
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${report}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Keep the blob alive until the browser has started consuming the download.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ---- Admin ----

export interface SystemStatus {
  app: string
  version: string
  env: string
  auth_required: boolean
  database: string
  python: string
  platform: string
  uptime_seconds: number
}

export function getSystemStatus() {
  return getJson<SystemStatus>('/api/admin/system/status')
}

export interface AdminHealthStatus {
  backend: string
  database: string
  warehouse: string
  ml_models: string
  authentication: string
}

export function getAdminHealth() {
  return getJson<AdminHealthStatus>('/api/admin/health')
}

export interface EtlStatus {
  loaded: boolean
  tables: Record<string, number | null>
  olist_dir: string
}

export function getEtlStatus() {
  return getJson<EtlStatus>('/api/admin/data/etl/status')
}

// ---- Users ----

export interface PublicUser {
  id: number
  username: string
  role: Role
  is_active: boolean
  created_at: string | null
}

export function getMe() {
  return getJson<{ user: PublicUser }>('/api/users/me')
}

export function listUsers() {
  return getJson<{ users: PublicUser[] }>('/api/users')
}

export function createUser(username: string, password: string, role: Role) {
  return postJson<{ user: PublicUser }>('/api/auth/register', { username, password, role })
}

export function updateUserRole(username: string, role: Role) {
  return request<{ user: PublicUser }>(`/api/users/${encodeURIComponent(username)}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
}

export interface RoleMetadata {
  name: string
  description: string
  permissions: Record<string, boolean>
}

export function getRoleMetadata() {
  return getJson<{ roles: RoleMetadata[] }>('/api/users/roles/metadata')
}

export function updateUserStatus(username: string, is_active: boolean) {
  return request<{ user: PublicUser }>(`/api/users/${encodeURIComponent(username)}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_active }),
  })
}

export function adminCreateUser(username: string, password: string, role: Role) {
  return postJson<{ user: PublicUser }>('/api/users', { username, password, role })
}

// ---- Administration ----

export interface WarehouseStatus {
  dialect: string
  schema_tables: string[]
  warehouse_tables: Record<string, number | null>
  expected_tables: number
  loaded_tables: number
  total_rows: number
  complete: boolean
  source: string
  min_date?: string | null
  max_date?: string | null
}

export function getWarehouseStatus() {
  return getJson<WarehouseStatus>('/api/admin/warehouse/status')
}

export interface ArtifactInfo {
  file: string
  size_bytes: number
  modified_at: string
}

export interface MlAdminStatus {
  models_dir: string
  artifacts: ArtifactInfo[]
  artifact_count: number
  metadata_entries: number
  features: MlFeature[]
  data_dir_exists: boolean
  retraining: string
}

export function getMlAdminStatus() {
  return getJson<MlAdminStatus>('/api/admin/ml/status')
}

export interface SystemSettings {
  app: string
  version: string
  env: string
  auth_required: boolean
  access_token_expire_minutes: number
  refresh_token_expire_minutes: number
  roles: Role[]
  llm: { enabled: boolean; provider: string; timeout_seconds: number }
  dataset: string
  reports: string[]
  secrets_exposed: boolean
}

export function getSystemSettings() {
  return getJson<SystemSettings>('/api/admin/settings')
}
