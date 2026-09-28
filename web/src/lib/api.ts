/**
 * Typed client for the SRE Memory Agent API.
 *
 * Field names mirror the backend models exactly (verified against live responses), so a
 * rename in the API surfaces here as a type error rather than as `undefined` in the UI.
 */

// ── primitives ────────────────────────────────────────────────

export type EventStatus = 'ok' | 'warn' | 'failed' | 'running' | 'skipped' | 'pending'

export type Outcome = 'recovered' | 'rolled-back' | 'escalated' | 'aborted' | 'in-progress' | null

export interface ExecutionEvent {
  id: string
  incident_id: string | null
  timestamp: string
  stage: string
  status: EventStatus
  message: string
  metadata: Record<string, unknown>
  _type?: 'event'
}

export type StreamPayload = ExecutionEvent & { _type?: string }

// ── memory ────────────────────────────────────────────────────

export interface MemoryRef {
  memory_id: string
  text: string
  kind: string
  document_id: string | null
  context: string | null
  tags: string[]
  metadata: Record<string, string>
  relevance: number | null
  occurred_start: string | null
  mentioned_at: string | null
  source_fact_ids: string[]
  source_facts: string[]
  retrieved_for: string | null
  influence: string | null
}

export interface BankSummary {
  bank_id: string
  memories: MemoryRef[]
}

export interface MemoryOverview {
  available: boolean
  detail: string
  banks: Record<string, BankSummary>
  counters: MemoryCounters
}

export interface MemoryCounters {
  retains: number
  recalls: number
  reflects: number
  failures: number
}

// ── test + verification ───────────────────────────────────────

export interface TestCaseResult {
  nodeid: string
  outcome: 'passed' | 'failed' | 'error' | 'skipped'
  message: string
  duration: number | null
}

export interface TestReport {
  suite_label: string
  exit_code: number
  total: number
  passed: number
  failed: number
  errors: number
  skipped: number
  duration: number
  cases: TestCaseResult[]
  raw_output: string
  exit_reason: string
  new_failures: string[]
  resolved_failures: string[]
}

export interface RegressionReport {
  original_error_resolved: boolean
  baseline_failing: string[]
  after_failing: string[]
  new_failures: string[]
  resolved_failures: string[]
  flaky: string[]
  blast_radius: string[]
  acceptable: boolean
  notes: string
}

export interface SandboxResult {
  backend: string
  isolated: boolean
  started: boolean
  patch_applied: boolean
  reproduce_report: TestReport | null
  error_reproduced: boolean
  test_report: TestReport | null
  full_report: TestReport | null
  output: string
  error: string | null
  duration_s: number
  workspace: string
  simulated: boolean
}

// ── review + patch ────────────────────────────────────────────

export type Severity = 'low' | 'medium' | 'high' | 'critical' | 'info'

export interface ReviewFinding {
  severity: Severity
  rule: string
  message: string
  file: string | null
  line: number | null
  reviewer: string
  memory_ref: string | null
  memory_text: string | null
}

export interface ReviewVerdict {
  decision: 'approve' | 'revise' | 'reject' | string
  summary: string
  findings: ReviewFinding[]
  reviewers_run: string[]
  cycles: number
  evaluated_at: string
}

export interface PatchFile {
  path: string
  content: string
}

export interface Patch {
  id: string
  incident_id: string
  attempt_number: number
  source: string
  root_cause: string
  why_this_happened: string
  proposed_fix: string
  files: PatchFile[]
  diff: string
  expected_outcome: string
  risk: string
  test_strategy: string
  model: string
  derived_from_incident: string | null
  addresses_root_cause: boolean
  summary: string
  latency_ms: number | null
}

export interface ValidationResult {
  ok: boolean
  errors: string[]
  warnings: string[]
  files_changed: number
  lines_added: number
  lines_removed: number
}

export interface RepairAttempt {
  number: number
  source: string
  strategy: string
  status: string
  patch: Partial<Patch> | null
  review: ReviewVerdict | null
  sandbox: SandboxResult | null
  regression: RegressionReport | null
  validation: ValidationResult | null
  duration_s: number | null
  error: string | null
  explanation: string | null
  started_at: string | null
  finished_at: string | null
}

// ── incident ──────────────────────────────────────────────────

export interface Classification {
  error_class: string
  confidence: number
  reasoning: string
  affected_files: string[]
  likely_fixability: string
  specialist: string | null
  evidence_required: string[]
  model: string | null
  source: string
}

export interface ComparabilityCheck {
  comparable: boolean
  confidence: number
  reason: string
  prior_incident_id: string | null
  prior_outcome: string | null
  prior_resolution: string | null
  prior_failed_fixes: string[]
  matched_on: string[]
  rejected_because: string[]
  source: string
}

export interface Evidence {
  error_message: string
  stack_trace: string
  logs: string
  source: string
  repo_path: string
  branch: string
  commit_sha: string
  commit_message: string
  previous_good_commit: string
  changed_files: string[]
  diff: string
  diff_summary: string
  dependency_changes: string[]
  env_info: Record<string, string>
  failing_tests: string[]
  test_report: TestReport | null
}

export interface IncidentMetrics {
  memories_recalled: number
  memories_reused: number
  memories_rejected: number
  attempts_used: number
  llm_calls: number
  tokens: number
  duration_s: number | null
}

export interface Incident {
  id: string
  repository: string
  repo_path: string
  branch: string
  commit_sha: string
  previous_good_commit: string
  error: string
  trigger: string
  status: string
  outcome: Outcome
  evidence: Evidence
  classification: Classification | null
  comparability: ComparabilityCheck | null
  memory_refs: MemoryRef[]
  convention_refs: MemoryRef[]
  rejected_memories: MemoryRef[]
  attempts: RepairAttempt[]
  metrics: IncidentMetrics
  root_cause: string | null
  final_resolution: string | null
  verification: string | null
  escalation_reason: string | null
  rollback_commit: string | null
  warnings: string[]
  degraded: boolean
  simulated: boolean
  run_mode: string
  created_at: string
  resolved_at: string | null
}

export interface IncidentSummary {
  id: string
  repository: string | null
  error: string | null
  error_class: string | null
  status: string | null
  outcome: Outcome
  run_mode: string | null
  attempts: number | null
  created_at: string | null
  resolved_at: string | null
  source?: 'live' | 'recorded'
  label?: string | null
}

// ── metrics + status ──────────────────────────────────────────

export interface DashboardMetrics {
  active_incidents: number
  total_incidents: number
  resolved: number
  rolled_back: number
  escalated: number
  by_status: Record<string, number>
  by_outcome: Record<string, number>
  by_error_class: Record<string, number>
  generated_at: string
}

export interface LearningRow {
  incidents: number
  attempts: number
  memories_recalled: number
  memories_reused: number
  first_attempt_success: number
  rollbacks: number
}

export interface LearningStats {
  total_incidents: number
  resolved: number
  rolled_back: number
  escalated: number
  repair_success_rate: number
  avg_attempts: number
  first_attempt_success_rate: number
  memories_recalled: number
  historical_fixes_reused: number
  failed_approaches_avoided: number
  regression_rate: number
  per_incident: LearningRow[]
}

export interface HindsightStatus {
  reachable: boolean
  detail: string
  version: string
  incident_bank: string
  convention_bank: string
}

export interface SystemStatus {
  healthy: boolean
  llm_ready: boolean
  hindsight_ready: boolean
  hindsight_detail: string
  sandbox_backend: string
  docker_available: boolean
  run_mode: string
  repo_present: boolean
  repo_path: string
  repo_commit: string
  active_incident_id: string | null
  banks: { incident: string; conventions: string }
  missing_credentials: string[]
  /** Healthy facts reported at startup. Not problems — `warnings` carries those. */
  notes: string[]
  warnings: string[]
  version: string
  hindsight_version: string
  metrics: DashboardMetrics
  learning: LearningStats
  memory: MemoryCounters
  memory_defense: string
  running: boolean
}

export interface MetricsPayload {
  dashboard: DashboardMetrics
  learning: LearningStats
  memory: MemoryCounters
  hindsight: HindsightStatus
}

export interface Scenario {
  key: string
  branch: string
  commit: string
  label: string
  description: string
  expectation: string
  error: string
}

export interface RecordedRun {
  id: string
  error: string | null
  error_class: string | null
  status: string | null
  outcome: Outcome
  run_mode: string | null
  attempts: number
  created_at: string | null
  label: string | null
  file: string
}

export interface RunbookPayload {
  available: boolean
  content: string
  detail?: string
  path?: string
  model_id?: string | null
}

// ── transport ─────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    })
  } catch (cause) {
    // A network failure is not a 500: the backend may simply not be running yet.
    throw new ApiError(
      'The backend is unreachable. Start it with `python scripts/serve.py`.',
      0,
      cause instanceof Error ? cause.message : undefined,
    )
  }

  if (!response.ok) {
    let detail: string | undefined
    try {
      const body = (await response.json()) as { detail?: string }
      detail = body?.detail
    } catch {
      detail = undefined
    }
    throw new ApiError(detail || `Request failed with HTTP ${response.status}`, response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  status: () => request<SystemStatus>('/status'),
  metrics: () => request<MetricsPayload>('/metrics'),

  incidents: (limit = 100, offset = 0) =>
    request<{ incidents: IncidentSummary[] }>(`/incidents?limit=${limit}&offset=${offset}`),
  incident: (id: string) => request<Incident>(`/incidents/${encodeURIComponent(id)}`),
  events: (id: string) =>
    request<{ events: ExecutionEvent[] }>(`/incidents/${encodeURIComponent(id)}/events`),

  startIncident: (body: { scenario?: string; replay?: boolean; trigger?: string }) =>
    request<{ incident: Incident; scenario: string | null }>('/incidents', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  approveRollback: (id: string) =>
    request<Record<string, unknown>>(`/incidents/${encodeURIComponent(id)}/rollback/approve`, {
      method: 'POST',
    }),

  memory: () => request<MemoryOverview>('/memory'),
  memorySearch: (q: string, bank: 'incident' | 'conventions' = 'incident', limit = 20) =>
    request<{ results: MemoryRef[]; available: boolean; detail?: string }>(
      `/memory/search?q=${encodeURIComponent(q)}&bank=${bank}&limit=${limit}`,
    ),
  runbook: (refresh = false) =>
    request<RunbookPayload>(`/memory/runbook${refresh ? '?refresh=true' : ''}`),
  conventions: () => request<{ conventions: string[]; bank: string }>('/conventions'),
  seedMemory: () => request<Record<string, unknown>>('/memory/seed', { method: 'POST' }),

  scenarios: () =>
    request<{ scenarios: Scenario[]; runs: RecordedRun[] }>('/demo/scenarios'),
  resetDemo: () => request<{ cleared: boolean; note: string }>('/demo/reset', { method: 'POST' }),
}

/** Absolute URL for the SSE endpoint (kept same-origin so the Vite proxy applies). */
export const STREAM_URL = `${BASE}/stream`
