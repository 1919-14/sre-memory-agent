/** Presentation helpers. No business logic lives here. */

export function localTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function localDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return `${date.toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })}, ${localTime(iso)}`
}

/** Compact relative age, e.g. `4m ago`. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`
  return localDateTime(iso)
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m ${rest}s`
}

/**
 * Rates reach the interface in two different units, and they must be named at the call site.
 *
 * `LearningStats.repair_success_rate` is already 0–100; confidences and memory relevance are
 * 0–1 fractions. An earlier version guessed from the magnitude (`value <= 1 ? value * 100 :
 * value`), which rendered a real 100% as _10000%_ and would have rendered a real 0.5% as
 * 50%. Guessing is the bug, so the unit is now explicit and defaults to the fraction form
 * that confidence values use.
 */
export type RateUnit = 'fraction' | 'percent'

export function percent(
  value: number | null | undefined,
  options: { digits?: number; from?: RateUnit } | number = {},
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const digits = typeof options === 'number' ? options : (options.digits ?? 0)
  const from: RateUnit = typeof options === 'number' ? 'fraction' : (options.from ?? 'fraction')
  const asPercent = from === 'fraction' ? value * 100 : value
  return `${asPercent.toFixed(digits)}%`
}

/**
 * Elapsed time as `mm:ss`, or `hh:mm:ss` past the hour.
 *
 * Used for measured wall-clock durations only. There is deliberately no formatting helper for
 * a completion estimate: the backend does not produce one, so the interface must not invent
 * one.
 */
export function clock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '00:00'
  const total = Math.max(0, Math.floor(seconds))
  const pad = (part: number) => String(part).padStart(2, '0')
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  return hours > 0
    ? `${pad(hours)}:${pad(minutes)}:${pad(rest)}`
    : `${pad(minutes)}:${pad(rest)}`
}

/** A measured duration in milliseconds, rendered for a per-stage label. */
export function millis(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (value < 1000) return `${Math.round(value)}ms`
  return `${(value / 1000).toFixed(1)}s`
}

export function shortSha(sha: string | null | undefined): string {
  if (!sha) return '—'
  return sha.slice(0, 8)
}

export function plural(count: number, singular: string, pluralForm?: string): string {
  return `${count} ${count === 1 ? singular : (pluralForm ?? `${singular}s`)}`
}

// ── label maps ────────────────────────────────────────────────

/** `connection-exhaustion` → `Connection exhaustion`. */
export function titleize(value: string | null | undefined): string {
  if (!value) return '—'
  const spaced = value.replace(/[_-]+/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

const STAGE_LABELS: Record<string, string> = {
  incident_detected: 'Detected',
  evidence_collected: 'Evidence collected',
  classified: 'Classified',
  memory_recalled: 'Memory recall',
  memory_search: 'Searching memory',
  comparability_checked: 'Comparability',
  fix_generated: 'Repair generated',
  review_gate: 'Review gate',
  sandbox_execution: 'Sandbox execution',
  verification: 'Verification',
  regression_check: 'Regression check',
  rollback: 'Rollback',
  resolved: 'Recovery',
  escalated: 'Escalated',
  memory_updated: 'Learning',
  memory_retained: 'Memory retained',
  aborted: 'Aborted',
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? titleize(stage)
}

const VARIANTS: Record<string, 'ok' | 'warn' | 'bad' | 'idle' | 'info'> = {
  recovered: 'ok',
  resolved: 'ok',
  approve: 'ok',
  passed: 'ok',
  comparable: 'ok',
  acceptable: 'ok',
  escalated: 'warn',
  revise: 'warn',
  review: 'warn',
  degraded: 'warn',
  'rolled-back': 'bad',
  rolled_back: 'bad',
  reject: 'bad',
  rejected: 'bad',
  failed: 'bad',
  'in-progress': 'info',
  running: 'info',
  analyzing: 'info',
  aborted: 'idle',
}

export function outcomeVariant(outcome: string | null | undefined) {
  return VARIANTS[outcome ?? ''] ?? 'idle'
}

export function outcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return 'In progress'
  return outcome.replace(/_/g, ' ').toUpperCase()
}

/**
 * Plain-language explanation for an error class, so the interface never shows a bare
 * taxonomy slug to someone who has not read the design document.
 */
const ERROR_CLASS_NOTES: Record<string, string> = {
  'connection-exhaustion': 'A connection pool ran out of capacity',
  'config-regression': 'A configuration change broke expected behaviour',
  'dependency-drift': 'A dependency version changed behaviour',
  'null-or-type': 'A value was missing or of the wrong type',
  'serialization-schema': 'A serialized shape no longer matches its reader',
  'timeout-retry': 'An operation exceeded its deadline',
  'concurrency-race': 'Timing between concurrent operations caused the failure',
  'build-toolchain': 'The build or toolchain itself failed',
  'test-defect': 'The test is wrong rather than the code',
  'auth-credential': 'A credential is missing, expired or rejected',
  infrastructure: 'The surrounding infrastructure is at fault',
  unknown: 'Not enough evidence to classify',
}

export function errorClassNote(errorClass: string | null | undefined): string | null {
  if (!errorClass) return null
  return ERROR_CLASS_NOTES[errorClass] ?? null
}

const SEVERITY_RANK: Record<string, number> = {
  info: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
}

export function severityRank(severity: string): number {
  return SEVERITY_RANK[severity] ?? 0
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
