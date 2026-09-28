/**
 * The live-run model.
 *
 * A judge must never be left staring at "Running…". This module turns the server's real event
 * stream into a per-stage picture of the investigation: which step is executing, which steps
 * are done, what each step actually produced, and whether an external dependency is holding
 * things up.
 *
 * Two rules keep it honest:
 *
 * 1. **Derived, never assumed.** A stage is only `completed` because the backend emitted a
 *    terminal event for it, and a step is only given evidence the backend actually sent.
 * 2. **No invented numbers.** There is no percentage, no ETA and no progress bar here. The only
 *    times shown are measured wall-clock values, and the only countdown is the retry window
 *    the provider itself reported.
 */

import type { ExecutionEvent, Incident } from './api'
import { percent, titleize } from './format'

export type StageState = 'waiting' | 'running' | 'completed' | 'failed' | 'skipped'

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'idle'

export interface RunStageSpec {
  key: string
  label: string
  /** Event `stage` values that belong to this step. */
  stages: string[]
  /** What this step does. Only ever shown as a description of the step, never as a result. */
  explainer: string
  /** Shown when the step is running and the backend has reported nothing new for a while. */
  waiting?: string
  /** True when the step depends on an external service, so a wait is a wait, not a stall. */
  external?: boolean
}

/**
 * The eleven steps of the investigation, in order. These are the steps this agent actually
 * executes — nothing is listed here that the backend does not do.
 */
export const RUN_STAGES: RunStageSpec[] = [
  {
    key: 'detected',
    label: 'Detected',
    stages: ['incident_detected'],
    explainer: 'Reading the failing build and collecting evidence.',
  },
  {
    key: 'classified',
    label: 'Classified',
    stages: ['classified'],
    explainer: 'Classifying the failure against the error taxonomy.',
  },
  {
    key: 'memory',
    label: 'Memory recall',
    stages: ['recalling_memory'],
    explainer: 'Querying Hindsight for comparable past incidents.',
    waiting: 'Waiting for the memory service to answer.',
    external: true,
  },
  {
    key: 'comparability',
    label: 'Comparability',
    stages: ['comparability_checked'],
    explainer: 'Judging whether the recalled memory actually applies to this failure.',
    waiting: 'Waiting for the model to return a verdict.',
    external: true,
  },
  {
    key: 'repair',
    label: 'Repair',
    stages: ['fix_generated'],
    explainer: 'Generating and validating a candidate repair.',
    waiting: 'The language model is generating and validating a candidate repair.',
    external: true,
  },
  {
    key: 'review',
    label: 'Review',
    stages: ['review_gate'],
    explainer: 'Running the review gate before anything executes.',
    waiting: 'Waiting for the model to return a verdict.',
    external: true,
  },
  {
    key: 'sandbox',
    label: 'Sandbox',
    stages: ['sandbox_execution'],
    explainer: 'Reproducing the failure, then testing the patched repository in isolation.',
    waiting: 'Waiting for the sandbox: the test run has to finish before it can report.',
  },
  {
    key: 'verification',
    label: 'Verification',
    stages: ['verification'],
    explainer: 'Checking the original failure is actually gone.',
  },
  {
    key: 'regression',
    label: 'Regression',
    stages: ['regression_check'],
    explainer: 'Comparing the full suite against the last known-good baseline.',
  },
  {
    key: 'recovery',
    label: 'Recovery',
    stages: ['resolved', 'rollback', 'escalated'],
    explainer: 'Deciding the terminal state of this incident.',
  },
  {
    key: 'learning',
    label: 'Learning',
    stages: ['memory_updated'],
    explainer: 'Writing this incident back to Hindsight, including what failed.',
    waiting: 'Waiting for the memory service to accept the write.',
    external: true,
  },
]

export interface RetryNotice {
  attempt: number
  retryInS: number
  operation: string
  reason: string
  /** When the notice arrived, so the countdown can be derived from real time. */
  at: string
}

export interface StageView {
  spec: RunStageSpec
  /** 1-based position in the investigation. */
  index: number
  state: StageState
  /** Raw backend status of the newest event for this step. */
  status: ExecutionEvent['status'] | null
  /** The newest message the backend sent for this step. */
  message: string | null
  events: ExecutionEvent[]
  startedAt: string | null
  endedAt: string | null
  /** Measured duration reported by the backend, or null when it has not finished. */
  durationMs: number | null
  retry: RetryNotice | null
}

export interface RunView {
  stages: StageView[]
  /** The step currently executing, or null once the run has stopped. */
  current: StageView | null
  /** The step with the newest event, running or not. */
  last: StageView | null
  reached: number
  total: number
  startedAt: string | null
  lastEventAt: string | null
  /** True while the agent is still working. */
  live: boolean
  /** The newest event overall, used for the "nothing new for a while" notice. */
  lastEvent: ExecutionEvent | null
}

// ── small readers for untyped event metadata ─────────────────

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function bool(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function strings(value: unknown): string[] {
  return list(value).filter((item): item is string => typeof item === 'string')
}

// ── derivation ────────────────────────────────────────────────

/**
 * Build the stage picture from the run's events.
 *
 * `live` must describe whether the agent is still working. It is passed in rather than guessed
 * because guessing it is exactly how an interface ends up claiming a step is "skipped" one
 * second into a run.
 */
export function buildRunView(events: ExecutionEvent[], live: boolean): RunView {
  const ordered = [...events].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
  const terminated = !live && ordered.length > 0

  const stages: StageView[] = RUN_STAGES.map((spec, position) => {
    const mine = ordered.filter((event) => spec.stages.includes(event.stage))
    const latest = mine.length > 0 ? mine[mine.length - 1] : null
    // The newest RUNNING event is when the current execution of this step began. Steps that
    // run again for a later attempt must not inherit the first attempt's clock.
    const opened = [...mine].reverse().find((event) => event.status === 'running') ?? mine[0] ?? null
    const closed = [...mine].reverse().find((event) => event.status !== 'running') ?? null

    let state: StageState
    if (!latest) state = terminated ? 'skipped' : 'waiting'
    else if (latest.status === 'running') state = 'running'
    else if (latest.status === 'failed') state = 'failed'
    else if (latest.status === 'skipped') state = 'skipped'
    else state = 'completed'

    const retryMeta = latest ? obj(latest.metadata) : {}
    const retryIn = num(retryMeta.retry_in_s)
    const retry = latest && bool(retryMeta.retry) && retryIn !== null
      ? {
          attempt: num(retryMeta.retry_attempt) ?? 0,
          retryInS: retryIn,
          operation: str(retryMeta.retry_operation) ?? 'memory operation',
          reason: str(retryMeta.reason) ?? 'provider rate limit',
          at: latest.timestamp,
        }
      : null

    return {
      spec,
      index: position + 1,
      state,
      status: latest?.status ?? null,
      message: latest?.message ?? null,
      events: mine,
      startedAt: opened?.timestamp ?? null,
      endedAt: closed?.timestamp ?? null,
      durationMs: closed ? num(obj(closed.metadata).duration_ms) : null,
      retry,
    }
  })

  const running = stages.find((stage) => stage.state === 'running') ?? null
  const withEvents = stages.filter((stage) => stage.events.length > 0)
  const last = withEvents.length > 0 ? withEvents[withEvents.length - 1] : null

  return {
    stages,
    current: running,
    last,
    reached: withEvents.length,
    total: stages.length,
    startedAt: ordered[0]?.timestamp ?? null,
    lastEventAt: ordered[ordered.length - 1]?.timestamp ?? null,
    live,
    lastEvent: ordered[ordered.length - 1] ?? null,
  }
}

/** Tone for a stage marker, from real state only. */
export function stageTone(stage: StageView): Tone {
  if (stage.state === 'running') return 'info'
  if (stage.state === 'failed') return 'bad'
  if (stage.state === 'completed') return stage.status === 'warn' ? 'warn' : 'ok'
  return 'idle'
}

// ── evidence ──────────────────────────────────────────────────

export interface EvidenceRow {
  label: string
  value: string
  tone?: Tone
}

function truncate(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value
}

/** The newest non-running event for a stage, which carries its result. */
function resultEvent(stage: StageView): ExecutionEvent | null {
  return [...stage.events].reverse().find((event) => event.status !== 'running') ?? null
}

/**
 * The real values a completed step produced, straight from the event metadata and the incident
 * document. A stage with nothing to report returns an empty list rather than a plausible guess.
 */
export function stageEvidence(stage: StageView, incident: Incident | null): EvidenceRow[] {
  const rows: EvidenceRow[] = []
  const event = resultEvent(stage)
  const meta = event?.metadata ?? {}
  const attemptNumber = num(meta.attempt)
  const attempt =
    attemptNumber !== null && incident
      ? (incident.attempts.find((item) => item.number === attemptNumber) ?? null)
      : null

  switch (stage.spec.key) {
    case 'detected': {
      const failure = str(meta.error)
      if (failure) rows.push({ label: 'Failure', value: truncate(failure, 180) })
      const changed = list(meta.changed_files).length
      if (changed > 0) rows.push({ label: 'Changed files', value: String(changed) })
      const failing = incident?.evidence.failing_tests.length ?? 0
      if (failing > 0) rows.push({ label: 'Failing tests', value: String(failing), tone: 'bad' })
      break
    }
    case 'classified': {
      const errorClass = str(meta.error_class)
      if (errorClass) rows.push({ label: 'Error class', value: titleize(errorClass) })
      const confidence = num(meta.confidence)
      if (confidence !== null) rows.push({ label: 'Confidence', value: percent(confidence) })
      const fixability = str(meta.fixability)
      if (fixability) rows.push({ label: 'Fixability', value: fixability })
      const specialist = str(meta.specialist)
      if (specialist) rows.push({ label: 'Specialist', value: specialist })
      break
    }
    case 'memory': {
      const memories = list(meta.memories).map(obj)
      if (memories.length > 0) {
        rows.push({ label: 'Memories retrieved', value: String(memories.length) })
        // Hindsight's retrieval score, reported as the score it is. It is not a percentage and
        // it is not bounded by 1, so showing it as one would be a fabricated ceiling.
        const best = Math.max(...memories.map((item) => num(item.relevance) ?? 0))
        rows.push({ label: 'Best retrieval score', value: best.toFixed(2) })
      } else if (event) {
        rows.push({ label: 'Memories retrieved', value: '0' })
      }
      if (incident && incident.convention_refs.length > 0) {
        rows.push({ label: 'Conventions consulted', value: String(incident.convention_refs.length) })
      }
      break
    }
    case 'comparability': {
      const comparable = bool(meta.comparable)
      if (comparable !== null) {
        rows.push({
          label: 'Verdict',
          value: comparable ? 'Comparable prior incident found' : 'No comparable incident',
          tone: comparable ? 'ok' : 'warn',
        })
      }
      const prior = incident?.comparability?.prior_incident_id ?? null
      if (prior) rows.push({ label: 'Prior incident', value: prior })
      const priorOutcome = incident?.comparability?.prior_outcome ?? null
      if (priorOutcome) {
        rows.push({
          label: 'Previous repair',
          value: titleize(priorOutcome),
          tone: priorOutcome === 'recovered' ? 'ok' : 'warn',
        })
      }
      for (const item of strings(meta.matched_on).slice(0, 3)) {
        rows.push({ label: 'Matched on', value: item, tone: 'ok' })
      }
      for (const item of strings(meta.rejected_because).slice(0, 2)) {
        rows.push({ label: 'Rejected because', value: item, tone: 'warn' })
      }
      break
    }
    case 'repair': {
      const source = str(meta.source)
      if (source) rows.push({ label: 'Source', value: titleize(source) })
      const files = strings(meta.files)
      if (files.length > 0) rows.push({ label: 'Files', value: files.join(', ') })
      const derived = str(meta.derived_from)
      if (derived) rows.push({ label: 'Adapted from', value: derived, tone: 'ok' })
      if (attempt?.validation) {
        rows.push({
          label: 'Validation',
          value: attempt.validation.ok ? 'passed' : 'failed',
          tone: attempt.validation.ok ? 'ok' : 'bad',
        })
        rows.push({
          label: 'Lines changed',
          value: `+${attempt.validation.lines_added} / -${attempt.validation.lines_removed}`,
        })
      }
      const errors = strings(meta.errors)
      if (errors.length > 0) rows.push({ label: 'Rejected because', value: errors.join('; '), tone: 'bad' })
      break
    }
    case 'review': {
      const decision = str(meta.decision)
      if (decision) {
        rows.push({
          label: 'Decision',
          value: decision.toUpperCase(),
          tone: decision === 'approve' ? 'ok' : decision === 'reject' ? 'bad' : 'warn',
        })
      }
      const severity = str(meta.max_severity)
      if (severity) rows.push({ label: 'Max severity', value: severity })
      const reviewers = strings(meta.reviewers)
      if (reviewers.length > 0) rows.push({ label: 'Reviewers', value: reviewers.join(', ') })
      const findings = list(meta.findings).length
      if (event) {
        rows.push({
          label: 'Findings',
          value: findings === 0 ? 'none' : String(findings),
          tone: findings === 0 ? 'ok' : 'warn',
        })
      }
      break
    }
    case 'sandbox': {
      const backend = str(meta.backend)
      if (backend) rows.push({ label: 'Backend', value: backend })
      const isolated = bool(meta.isolated)
      if (isolated !== null) {
        rows.push({ label: 'Isolated', value: isolated ? 'yes' : 'no', tone: isolated ? 'ok' : 'warn' })
      }
      const reproduced = bool(meta.error_reproduced)
      if (reproduced !== null) {
        rows.push({
          label: 'Original failure',
          value: reproduced ? 'reproduced' : 'not reproduced',
          tone: reproduced ? 'ok' : 'bad',
        })
      }
      const verify = str(meta.verify)
      if (verify) rows.push({ label: 'After patch', value: verify })
      const full = str(meta.full)
      if (full) rows.push({ label: 'Full suite', value: full })
      const seconds = num(meta.duration_s)
      if (seconds !== null) rows.push({ label: 'Duration', value: `${seconds.toFixed(1)}s` })
      const error = str(meta.error)
      if (error) rows.push({ label: 'Sandbox error', value: truncate(error, 180), tone: 'bad' })
      break
    }
    case 'verification': {
      const resolved = bool(meta.original_error_resolved)
      if (resolved !== null) {
        rows.push({
          label: 'Original failure resolved',
          value: resolved ? 'yes' : 'no',
          tone: resolved ? 'ok' : 'bad',
        })
      }
      const reproduce = str(meta.reproduce)
      if (reproduce) rows.push({ label: 'Before patch', value: reproduce, tone: 'bad' })
      const verify = str(meta.verify)
      if (verify) rows.push({ label: 'After patch', value: verify, tone: 'ok' })
      break
    }
    case 'regression': {
      const newFailures = strings(meta.new_failures)
      const resolved = bool(meta.original_error_resolved)
      if (resolved !== null) {
        rows.push({
          label: 'Original error resolved',
          value: resolved ? 'yes' : 'no',
          tone: resolved ? 'ok' : 'bad',
        })
      }
      rows.push({
        label: 'New failures',
        value: String(newFailures.length),
        tone: newFailures.length === 0 ? 'ok' : 'bad',
      })
      const flaky = strings(meta.flaky).length
      if (flaky > 0) rows.push({ label: 'Flaky, not counted', value: String(flaky), tone: 'warn' })
      const full = str(meta.notes)
      if (full) rows.push({ label: 'Result', value: truncate(full, 180) })
      break
    }
    case 'recovery': {
      const outcome = incident?.outcome ?? null
      if (outcome) {
        rows.push({
          label: 'Outcome',
          value: titleize(outcome),
          tone: outcome === 'recovered' ? 'ok' : outcome === 'escalated' ? 'warn' : 'bad',
        })
      }
      const resolution = str(meta.resolution) ?? incident?.final_resolution ?? null
      if (resolution) rows.push({ label: 'Resolution', value: truncate(resolution, 200) })
      const verification = str(meta.verification)
      if (verification) rows.push({ label: 'Verification', value: truncate(verification, 200) })
      const restored = str(meta.restored_to)
      if (restored) rows.push({ label: 'Restored to', value: restored.slice(0, 8), tone: 'warn' })
      break
    }
    case 'learning': {
      const bank = str(meta.bank)
      if (bank) rows.push({ label: 'Bank', value: bank })
      const tags = strings(meta.tags)
      if (tags.length > 0) rows.push({ label: 'Tags', value: String(tags.length) })
      const label = str(meta.label)
      if (label) rows.push({ label: 'Recorded as', value: titleize(label) })
      if (incident) {
        rows.push({ label: 'Memories recalled', value: String(incident.metrics.memories_recalled) })
        rows.push({ label: 'Fixes reused', value: String(incident.metrics.memories_reused) })
      }
      break
    }
    default:
      break
  }

  return rows
}

// ── summary ───────────────────────────────────────────────────

export interface RunSummary {
  outcome: string
  tone: Tone
  headline: string
  facts: string[]
}

/**
 * The post-run summary, built entirely from the incident and its events.
 *
 * Facts are only listed when the backend supports them, so a run that reused no memory simply
 * does not claim to have reused any.
 */
export function runSummary(incident: Incident, view: RunView, events: ExecutionEvent[]): RunSummary {
  const outcome = incident.outcome ?? 'in-progress'
  const tone: Tone =
    outcome === 'recovered' ? 'ok' : outcome === 'escalated' ? 'warn' : outcome === 'in-progress' ? 'info' : 'bad'

  // The verification event is the one that carries both sides of the comparison: the
  // unpatched run and the patched run.
  const sandbox = [...events].reverse().find(
    (event) => event.stage === 'sandbox_execution' && event.status !== 'running',
  )
  const verification = [...events].reverse().find(
    (event) => event.stage === 'verification' && event.status !== 'running',
  )
  const before = countFromSummary(str(verification?.metadata?.reproduce)) ??
    countFromSummary(str(sandbox?.metadata?.reproduce))
  const after = countFromSummary(str(verification?.metadata?.verify)) ??
    countFromSummary(str(sandbox?.metadata?.verify))
  const failingAtStart = incident.evidence.failing_tests.length

  const headline =
    before !== null && after !== null
      ? `${before} failing → ${after} failing`
      : failingAtStart > 0
        ? `${failingAtStart} failing test${failingAtStart === 1 ? '' : 's'} detected`
        : 'No failing tests were detected'

  // Proposals and verified attempts are counted separately because they are genuinely
  // different numbers: a proposal blocked at the review gate never executed anything, and
  // collapsing the two would overstate what ran.
  const proposals = events.filter(
    (event) => event.stage === 'fix_generated' && event.status === 'ok',
  ).length
  const blocked = events.filter(
    (event) =>
      event.stage === 'review_gate' &&
      (event.metadata.decision === 'revise' || event.metadata.decision === 'reject'),
  ).length

  const facts: string[] = []
  facts.push(
    `${incident.metrics.attempts_used} verified attempt${
      incident.metrics.attempts_used === 1 ? '' : 's'
    }`,
  )
  if (proposals > incident.metrics.attempts_used) {
    facts.push(`${proposals} proposals generated`)
  }
  if (blocked > 0) {
    facts.push(`${blocked} blocked at the review gate before execution`)
  }
  if (incident.metrics.memories_reused > 0) {
    facts.push(`historical memory reused (${incident.metrics.memories_reused})`)
  } else if (incident.metrics.memories_recalled > 0) {
    facts.push(`${incident.metrics.memories_recalled} memories consulted, none applicable`)
  } else {
    facts.push('no historical memory was applicable')
  }

  const regression = [...events].reverse().find(
    (event) => event.stage === 'regression_check' && event.status !== 'running',
  )
  const newFailures = regression ? strings(obj(regression.metadata).new_failures).length : null
  if (newFailures !== null) {
    facts.push(newFailures === 0 ? 'regression clean' : `${newFailures} new failure(s)`)
  }
  const full = str(sandbox?.metadata?.full ?? verification?.metadata?.full)
  if (full) facts.push(`full suite ${full}`)

  const retained = view.stages.find((stage) => stage.spec.key === 'learning')
  if (retained && retained.state === 'completed') facts.push('memory retained')

  return {
    outcome: outcome.replace(/_/g, ' ').toUpperCase(),
    tone,
    headline,
    facts,
  }
}

/** Pull the failing count out of a pytest summary line such as "4 passed, 0 failed, ...". */
function countFromSummary(value: string | null): string | null {
  if (!value) return null
  const match = /(\d+)\s+failed/.exec(value)
  return match ? match[1] : null
}

/** `scenario/concurrency` → `concurrency`, so a follow-up run can repeat the same failure. */
export function scenarioOf(branch: string | null | undefined): string | null {
  if (!branch) return null
  const match = /^scenario\/(.+)$/.exec(branch)
  return match ? match[1] : null
}
