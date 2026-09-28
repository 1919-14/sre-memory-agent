import { type ReactNode } from 'react'

import type { ExecutionEvent, Incident, RepairAttempt } from '../lib/api'
import { duration, localTime, percent, plural, shortSha, titleize } from '../lib/format'
import { DiffViewer } from './DiffViewer'
import { MemoryCard } from './MemoryCard'
import { KV, SeverityTag, StatusMark, Tag, type Variant } from './primitives'
import { TestPanel } from './TestPanel'

interface Stage {
  key: string
  label: string
  variant: Variant
  headline: string
  detail?: ReactNode
  open?: boolean
}

/** The event stage names that mark each step, for timestamp correlation. */
function stampFor(events: ExecutionEvent[], ...stages: string[]): string | null {
  for (const stage of stages) {
    const match = events.find((event) => event.stage === stage)
    if (match) return match.timestamp
  }
  return null
}

function attemptStages(attempt: RepairAttempt): Stage[] {
  const stages: Stage[] = []
  const patch = attempt.patch
  const number = attempt.number

  stages.push({
    key: `repair-${number}`,
    label: `Repair attempt ${number}`,
    variant: attempt.error ? 'bad' : patch?.proposed_fix ? 'ok' : 'idle',
    headline:
      (attempt.error && `Could not produce a patch — ${attempt.error}`) ||
      patch?.summary ||
      titleize(attempt.strategy),
    detail: patch?.proposed_fix ? (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone="neutral">{patch.source ?? attempt.source}</Tag>
          {patch.model ? <Tag tone="neutral">{patch.model}</Tag> : null}
          {patch.derived_from_incident ? (
            <Tag tone="accent" title="Adapted from a recalled incident">
              from {patch.derived_from_incident}
            </Tag>
          ) : null}
        </div>
        {patch.root_cause ? (
          <div>
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Root cause
            </div>
            <p className="mt-1 text-meta">{patch.root_cause}</p>
          </div>
        ) : null}
        {patch.proposed_fix ? (
          <div>
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Proposed fix
            </div>
            <p className="mt-1 text-meta">{patch.proposed_fix}</p>
          </div>
        ) : null}
        {patch.why_this_happened ? (
          <div>
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Why this happened
            </div>
            <p className="mt-1 text-meta text-status-idle">{patch.why_this_happened}</p>
          </div>
        ) : null}
        {attempt.validation ? (
          <KV k="Validation" mono>
            {attempt.validation.ok ? 'passed' : 'failed'} · {attempt.validation.files_changed} file(s),{' '}
            +{attempt.validation.lines_added}/-{attempt.validation.lines_removed}
          </KV>
        ) : null}
        {patch.diff ? <DiffViewer diff={patch.diff} /> : null}
      </div>
    ) : undefined,
  })

  if (attempt.review) {
    const verdict = attempt.review
    stages.push({
      key: `review-${number}`,
      label: 'Review gate',
      variant: verdict.decision === 'approve' ? 'ok' : verdict.decision === 'reject' ? 'bad' : 'warn',
      headline: `${verdict.decision.toUpperCase()} — ${verdict.summary}`,
      detail: (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {verdict.reviewers_run.map((reviewer) => (
              <Tag key={reviewer} tone="neutral">
                {reviewer}
              </Tag>
            ))}
            <Tag tone="neutral">{plural(verdict.cycles, 'cycle')}</Tag>
          </div>
          {verdict.findings.length === 0 ? (
            <p className="text-meta text-status-idle">No findings were raised.</p>
          ) : (
            <ul className="divide-y divide-hair border-t-2 border-hair">
              {verdict.findings.map((finding, index) => (
                <li key={`${finding.rule}-${index}`} className="flex items-start gap-3 py-3">
                  <SeverityTag severity={finding.severity} />
                  <div className="min-w-0">
                    <div className="text-meta font-bold">{finding.rule}</div>
                    <p className="mt-0.5 text-meta text-status-idle">{finding.message}</p>
                    {finding.memory_text ? (
                      <p className="mt-2 border-l-2 border-accent pl-3 text-micro text-status-idle">
                        Against a remembered rule: {finding.memory_text}
                      </p>
                    ) : null}
                  </div>
                  <span className="ml-auto shrink-0 font-mono text-micro text-status-idle">
                    {finding.reviewer}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ),
    })
  }

  if (attempt.sandbox) {
    const sandbox = attempt.sandbox
    const verify = sandbox.test_report
    stages.push({
      key: `sandbox-${number}`,
      label: 'Sandbox execution',
      variant: sandbox.error_reproduced && verify && verify.failed === 0 ? 'ok' : 'bad',
      headline: sandbox.error_reproduced
        ? `Failure reproduced, then ${
            verify ? `${verify.passed} passed / ${verify.failed} failed` : 're-tested'
          }`
        : 'The failure was not reproduced in isolation',
      detail: (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-px bg-hair sm:grid-cols-4">
            {[
              { label: 'Backend', value: sandbox.backend },
              { label: 'Isolated', value: sandbox.isolated ? 'yes' : 'no' },
              { label: 'Patch applied', value: sandbox.patch_applied ? 'yes' : 'no' },
              { label: 'Duration', value: duration(sandbox.duration_s) },
            ].map((item) => (
              <div key={item.label} className="bg-paper px-3 py-2">
                <div className="text-label font-black uppercase tracking-widest text-status-idle">
                  {item.label}
                </div>
                <div className="mt-0.5 font-mono text-micro">{item.value}</div>
              </div>
            ))}
          </div>
          {sandbox.simulated ? (
            <p className="border-l-2 border-status-warn pl-3 text-micro text-status-warn">
              This execution is marked simulated by the backend, not a live sandbox run.
            </p>
          ) : null}
          <TestPanel title="Reproduce the failure (unpatched)" report={sandbox.reproduce_report} />
          <TestPanel title="Verify the fix (targeted)" report={sandbox.test_report} />
          <TestPanel title="Full suite" report={sandbox.full_report} />
          {sandbox.error ? (
            <pre className="code-surface max-h-40 overflow-auto p-3 text-micro">{sandbox.error}</pre>
          ) : null}
        </div>
      ),
    })
  }

  if (attempt.regression) {
    const regression = attempt.regression
    stages.push({
      key: `regression-${number}`,
      label: 'Regression check',
      variant: regression.acceptable && regression.original_error_resolved ? 'ok' : 'bad',
      headline: regression.acceptable
        ? 'No unacceptable regression introduced'
        : `Regression detected — ${plural(regression.new_failures.length, 'new failure')}`,
      detail: (
        <div>
          <dl>
            <KV k="Original error resolved">
              <StatusMark
                variant={regression.original_error_resolved ? 'ok' : 'bad'}
                label={regression.original_error_resolved ? 'yes' : 'no'}
              />
            </KV>
            <KV k="New failures" mono>
              {regression.new_failures.length}
            </KV>
            <KV k="Resolved failures" mono>
              {regression.resolved_failures.length}
            </KV>
            <KV k="Flaky (not counted)" mono>
              {regression.flaky.length}
            </KV>
          </dl>
          {regression.notes ? <p className="mt-3 text-meta text-status-idle">{regression.notes}</p> : null}
          {regression.new_failures.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {regression.new_failures.map((item) => (
                <li key={item} className="font-mono text-micro text-status-bad">
                  {item}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ),
    })
  }

  return stages
}

/** Build the ordered investigation stages from an incident, using only real fields. */
export function buildStages(incident: Incident): Stage[] {
  const stages: Stage[] = []
  const evidence = incident.evidence

  stages.push({
    key: 'detected',
    label: 'Detected',
    variant: 'ok',
    headline: `${evidence.failing_tests.length > 0 ? plural(evidence.failing_tests.length, 'failing test') : 'Failure'} on ${incident.branch || 'branch'}`,
    detail: (
      <div className="space-y-4">
        <dl>
          <KV k="Trigger" mono>
            {incident.trigger}
          </KV>
          <KV k="Commit" mono>
            {shortSha(incident.commit_sha)}
          </KV>
          <KV k="Last known good" mono>
            {shortSha(incident.previous_good_commit)}
          </KV>
          <KV k="Changed files" mono>
            {evidence.changed_files.length}
          </KV>
          <KV k="Environment" mono>
            {[evidence.env_info?.python, evidence.env_info?.platform].filter(Boolean).join(' · ') || '—'}
          </KV>
        </dl>
        {evidence.error_message ? (
          <pre className="code-surface max-h-48 overflow-auto p-3 text-micro">
            {evidence.error_message}
          </pre>
        ) : null}
        {evidence.diff ? <DiffViewer diff={evidence.diff} label="Commit diff" /> : null}
      </div>
    ),
  })

  if (incident.classification) {
    const classification = incident.classification
    stages.push({
      key: 'classified',
      label: 'Classified',
      variant: classification.likely_fixability === 'code-fixable' ? 'ok' : 'warn',
      headline: titleize(classification.error_class),
      detail: (
        <div className="space-y-3">
          <dl>
            <KV k="Confidence" mono>
              {percent(classification.confidence)}
            </KV>
            <KV k="Fixability" mono>
              {classification.likely_fixability}
            </KV>
            <KV k="Decided by" mono>
              {classification.source}
              {classification.model ? ` (${classification.model})` : ''}
            </KV>
            {classification.affected_files.length > 0 ? (
              <KV k="Affected files" mono>
                {classification.affected_files.join(', ')}
              </KV>
            ) : null}
          </dl>
          {classification.reasoning ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Reasoning
              </div>
              <p className="mt-1 text-meta">{classification.reasoning}</p>
            </div>
          ) : null}
        </div>
      ),
    })
  }

  const recalled = [...incident.memory_refs, ...incident.convention_refs]
  stages.push({
    key: 'memory',
    label: 'Memory recall',
    variant: recalled.length > 0 ? 'ok' : 'idle',
    headline:
      recalled.length > 0
        ? `${plural(recalled.length, 'memory', 'memories')} retrieved from Hindsight`
        : 'No relevant history in Hindsight',
    detail:
      recalled.length > 0 ? (
        <div className="space-y-4">
          {incident.memory_refs.length > 0 ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Historical incidents
              </div>
              <div className="mt-3 space-y-4">
                {incident.memory_refs.map((ref) => (
                  <MemoryCard
                    key={ref.memory_id}
                    memory={ref}
                    against={{
                      error_class: incident.classification?.error_class ?? null,
                      repository: incident.repository,
                    }}
                  />
                ))}
              </div>
            </div>
          ) : null}
          {incident.convention_refs.length > 0 ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Repository conventions
              </div>
              <div className="mt-3 space-y-4">
                {incident.convention_refs.map((ref) => (
                  <MemoryCard key={ref.memory_id} memory={ref} compact />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-meta text-status-idle">
          Nothing comparable had been recorded for this service, so the agent started from zero.
        </p>
      ),
  })

  if (incident.comparability) {
    const check = incident.comparability
    stages.push({
      key: 'comparability',
      label: 'Comparability',
      variant: check.comparable ? 'ok' : 'warn',
      headline: check.comparable
        ? `Historical incident judged comparable (${percent(check.confidence)})`
        : 'No recalled incident was comparable',
      detail: (
        <div className="space-y-4">
          <p className="text-meta">{check.reason}</p>
          <dl>
            <KV k="Decided by" mono>
              {check.source}
            </KV>
            {check.prior_incident_id ? (
              <KV k="Prior incident" mono>
                {check.prior_incident_id}
              </KV>
            ) : null}
            {check.prior_outcome ? (
              <KV k="Prior outcome" mono>
                {check.prior_outcome}
              </KV>
            ) : null}
          </dl>
          {check.matched_on.length > 0 ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Evidence for
              </div>
              <ul className="mt-2 space-y-1">
                {check.matched_on.map((item) => (
                  <li key={item} className="flex items-center gap-2 text-meta">
                    <span aria-hidden className="h-1.5 w-1.5 bg-status-ok" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {check.rejected_because.length > 0 ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Evidence against
              </div>
              <ul className="mt-2 space-y-1">
                {check.rejected_because.map((item) => (
                  <li key={item} className="flex items-center gap-2 text-meta">
                    <span aria-hidden className="h-1.5 w-1.5 bg-status-warn" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {check.prior_resolution ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Prior resolution
              </div>
              <p className="mt-1 text-meta">{check.prior_resolution}</p>
            </div>
          ) : null}
          {check.prior_failed_fixes.length > 0 ? (
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Approaches that already failed
              </div>
              <ul className="mt-1 space-y-1">
                {check.prior_failed_fixes.map((item) => (
                  <li key={item} className="text-meta text-status-idle">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ),
    })
  }

  incident.attempts.forEach((attempt) => stages.push(...attemptStages(attempt)))

  if (incident.outcome) {
    const recovered = incident.outcome === 'recovered'
    const escalated = incident.outcome === 'escalated'
    stages.push({
      key: 'recovery',
      label: recovered ? 'Recovery' : escalated ? 'Escalation' : 'Rollback',
      variant: recovered ? 'ok' : escalated ? 'warn' : 'bad',
      headline: recovered
        ? incident.verification || 'The fix was verified in the sandbox.'
        : escalated
          ? incident.escalation_reason || 'Handed to a human operator.'
          : `Repository restored to ${shortSha(incident.rollback_commit)}.`,
      detail: (
        <dl>
          {incident.final_resolution ? (
            <KV k="Resolution" align="stack">
              {incident.final_resolution}
            </KV>
          ) : null}
          {incident.escalation_reason ? (
            <KV k="Escalation" align="stack">
              {incident.escalation_reason}
            </KV>
          ) : null}
          {incident.rollback_commit ? (
            <KV k="Restored to" mono>
              {shortSha(incident.rollback_commit)}
            </KV>
          ) : null}
          <KV k="Attempts used" mono>
            {incident.metrics.attempts_used}
          </KV>
          <KV k="Duration" mono>
            {duration(incident.metrics.duration_s)}
          </KV>
        </dl>
      ),
    })
  }

  stages.push({
    key: 'learning',
    label: 'Learning',
    variant: 'ok',
    headline: 'Trajectory written back to Hindsight',
    detail: (
      <div className="space-y-3">
        <p className="text-meta text-status-idle">
          This incident — including the approaches that failed — is now evidence for future
          failures of the same class.
        </p>
        <dl>
          <KV k="Memories recalled" mono>
            {incident.metrics.memories_recalled}
          </KV>
          <KV k="Memories reused" mono>
            {incident.metrics.memories_reused}
          </KV>
          <KV k="Conventions consulted" mono>
            {incident.convention_refs.length}
          </KV>
          <KV k="Run mode" mono>
            {incident.run_mode}
          </KV>
        </dl>
        {incident.degraded ? (
          <p className="border-l-2 border-status-warn pl-3 text-micro text-status-warn">
            This run was degraded: {incident.warnings.join(' ')}
          </p>
        ) : null}
      </div>
    ),
  })

  return stages
}

/** Renders the numbered investigation timeline. */
export function IncidentTimeline({
  incident,
  events,
}: {
  incident: Incident
  events: ExecutionEvent[]
}) {
  const stages = buildStages(incident)

  return (
    <ol className="relative">
      {stages.map((stage, index) => {
        const isLast = index === stages.length - 1
        return (
          <li key={stage.key} className="relative flex gap-5 pb-8 last:pb-0">
            {/* connector */}
            {!isLast ? (
              <span aria-hidden className="absolute left-[13px] top-8 h-[calc(100%-1.5rem)] w-0.5 bg-hair-strong" />
            ) : null}

            <div className="relative z-10 flex flex-col items-center">
              <span
                aria-hidden
                className={`grid h-7 w-7 shrink-0 place-items-center border-2 font-mono text-micro font-bold ${
                  stage.variant === 'ok'
                    ? 'border-ink bg-ink text-paper'
                    : stage.variant === 'bad'
                      ? 'border-status-bad bg-status-bad text-paper'
                      : stage.variant === 'warn'
                        ? 'border-status-warn bg-status-warn text-paper'
                        : 'border-hair-strong bg-paper text-status-idle'
                }`}
              >
                {String(index + 1).padStart(2, '0')}
              </span>
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="text-meta font-black uppercase tracking-widest text-ink">
                  {stage.label}
                </h3>
                <span className="font-mono text-micro text-status-idle">
                  {localTime(stampFor(events, stage.key))}
                </span>
              </div>
              <p className="mt-1.5 text-lead text-ink">{stage.headline}</p>
              {stage.detail ? (
                <details className="group mt-3">
                  <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent">
                    <span className="inline-block transition-transform duration-200 group-open:rotate-90">
                      +
                    </span>
                    Evidence
                  </summary>
                  <div className="mt-4 animate-fade-rise border-l-2 border-hair pl-5">{stage.detail}</div>
                </details>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
