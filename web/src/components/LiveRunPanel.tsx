import {
  Activity,
  ArrowRight,
  Box,
  BrainCircuit,
  Check,
  Circle,
  Database,
  FlaskConical,
  LifeBuoy,
  Loader2,
  Minus,
  Play,
  Radar,
  Scale,
  ShieldCheck,
  Tags,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useMemo } from 'react'

import type { ExecutionEvent, Incident } from '../lib/api'
import { clock, millis, percent, titleize } from '../lib/format'
import { useTicker } from '../lib/hooks'
import {
  buildRunView,
  runSummary,
  stageEvidence,
  stageTone,
  type StageState,
  type StageView,
} from '../lib/run'
import { ActivityStream } from './ActivityStream'
import { KV, Panel, StatusMark, Tag, type Variant } from './primitives'

const STAGE_ICON: Record<string, LucideIcon> = {
  detected: Radar,
  classified: Tags,
  memory: BrainCircuit,
  comparability: Scale,
  repair: Wrench,
  review: ShieldCheck,
  sandbox: Box,
  verification: FlaskConical,
  regression: Activity,
  recovery: LifeBuoy,
  learning: Database,
}

const STATE_LABEL: Record<StageState, string> = {
  waiting: 'Waiting',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped',
}

const STATE_GLYPH: Record<StageState, LucideIcon> = {
  waiting: Circle,
  running: Loader2,
  completed: Check,
  failed: X,
  skipped: Minus,
}

const TONE_VARIANT: Record<string, Variant> = {
  ok: 'ok',
  warn: 'warn',
  bad: 'bad',
  info: 'info',
  idle: 'idle',
}

function secondsBetween(fromIso: string | null, toMs: number): number | null {
  if (!fromIso) return null
  const from = Date.parse(fromIso)
  if (Number.isNaN(from)) return null
  return Math.max(0, (toMs - from) / 1000)
}

/** One cell of the execution strip: a real step, in its real state. */
function StageCell({ stage, now }: { stage: StageView; now: number }) {
  const Icon = STAGE_ICON[stage.spec.key] ?? Circle
  const Glyph = STATE_GLYPH[stage.state]
  const tone = stageTone(stage)

  const timing =
    stage.state === 'running'
      ? clock(secondsBetween(stage.startedAt, now) ?? 0)
      : stage.durationMs !== null
        ? millis(stage.durationMs)
        : stage.state === 'completed' || stage.state === 'failed'
          ? clock(
              Math.max(
                0,
                (Date.parse(stage.endedAt ?? '') - Date.parse(stage.startedAt ?? '')) / 1000 || 0,
              ),
            )
          : ''

  return (
    <div className={`px-3 py-3 ${stage.state === 'running' ? 'bg-muted' : 'bg-paper'}`}>
      <div className="flex items-center justify-between gap-2">
        <Icon size={13} strokeWidth={2.5} className="shrink-0 text-ink" aria-hidden />
        <span className="font-mono text-micro tabular text-status-idle">
          {String(stage.index).padStart(2, '0')}
        </span>
      </div>
      <div className="mt-2 text-label font-black uppercase tracking-wide text-ink">
        {stage.spec.label}
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <Glyph
          size={10}
          strokeWidth={3}
          aria-hidden
          className={`shrink-0 ${stage.state === 'running' ? 'animate-spin' : ''} ${
            tone === 'ok'
              ? 'text-status-ok'
              : tone === 'warn'
                ? 'text-status-warn'
                : tone === 'bad'
                  ? 'text-status-bad'
                  : tone === 'info'
                    ? 'text-status-info'
                    : 'text-status-idle'
          }`}
        />
        <span
          className={`text-label font-bold uppercase tracking-wide ${
            tone === 'ok'
              ? 'text-status-ok'
              : tone === 'warn'
                ? 'text-status-warn'
                : tone === 'bad'
                  ? 'text-status-bad'
                  : tone === 'info'
                    ? 'text-status-info'
                    : 'text-status-idle'
          }`}
        >
          {STATE_LABEL[stage.state]}
        </span>
      </div>
      <div className="mt-1 font-mono text-micro tabular text-status-idle">{timing || '\u00a0'}</div>
    </div>
  )
}

/**
 * The live execution panel.
 *
 * Shown while the agent is working and kept on screen once it stops, so the run can be read from
 * start to finish without the interface ever looking frozen. Every figure here — the elapsed
 * clock, each stage's duration, each evidence row — comes from a backend event or the incident
 * document. Nothing is estimated, and there is deliberately no progress bar.
 */
export function LiveRunPanel({
  incident,
  events,
  live,
  onRunSimilar,
  similarBusy = false,
  onViewInvestigation,
}: {
  incident: Incident
  events: ExecutionEvent[]
  live: boolean
  onRunSimilar?: () => void
  similarBusy?: boolean
  onViewInvestigation?: () => void
}) {
  const now = useTicker(live)
  const view = useMemo(() => buildRunView(events, live), [events, live])

  const focus = view.current ?? view.last
  const summary = useMemo(() => runSummary(incident, view, events), [incident, view, events])

  const startedAt = incident.created_at ?? view.startedAt
  const endMs = live
    ? now
    : Date.parse(view.lastEventAt ?? incident.resolved_at ?? incident.created_at)
  const totalSeconds = secondsBetween(startedAt, live ? now : endMs) ?? 0
  const stageSeconds = focus ? secondsBetween(focus.startedAt, now) : null

  // A step that has produced nothing new for a while is reported as waiting on its dependency
  // rather than left to look stalled. The sentence is the step's own description.
  const sinceLastEvent = view.lastEventAt ? (now - Date.parse(view.lastEventAt)) / 1000 : 0
  const stalled = live && sinceLastEvent > 7
  const retry = focus?.retry ?? null
  const retryRemaining = retry
    ? Math.max(0, Math.round(retry.retryInS - (now - Date.parse(retry.at)) / 1000))
    : 0

  const comparability = view.stages.find((stage) => stage.spec.key === 'comparability')

  // The memory-reuse story, told from real fields: the recalled document, the judge's
  // confidence, and what happened to the incident that record describes.
  const topMemory = incident.memory_refs[0] ?? null
  const priorIncident = topMemory?.document_id ?? null
  const incidentalPrior = incident.comparability?.prior_incident_id ?? null
  const similarity = incident.comparability?.confidence ?? null
  const priorRepair =
    incident.comparability?.prior_outcome ?? topMemory?.metadata?.outcome ?? null

  const comparable = incident.comparability?.comparable === true
  const comparabilityDone = comparability?.state === 'completed' || comparability?.state === 'failed'

  const evidenceBlocks = view.stages
    .map((stage) => ({ stage, rows: stageEvidence(stage, incident) }))
    .filter((block) => block.rows.length > 0)

  return (
    <Panel className={live ? 'overflow-hidden border-accent' : 'overflow-hidden'}>
      {/* ── header: state, elapsed, stage count ─────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4 border-b-2 border-ink px-6 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <StatusMark
            variant={live ? 'info' : TONE_VARIANT[summary.tone] ?? 'idle'}
            label={live ? 'Running' : summary.outcome}
          />
          <span className="font-mono text-micro text-status-idle">{incident.id}</span>
          {incident.branch ? <Tag tone="neutral">{incident.branch}</Tag> : null}
          <Tag tone={incident.run_mode === 'live' ? 'ok' : 'neutral'}>{incident.run_mode}</Tag>
        </div>
        <div className="flex items-center gap-8">
          <div>
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Elapsed
            </div>
            <div className="mt-0.5 font-mono text-h3 tabular">{clock(totalSeconds)}</div>
          </div>
          <div>
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Steps reached
            </div>
            <div className="mt-0.5 font-mono text-h3 tabular">
              {view.reached}/{view.total}
            </div>
          </div>
        </div>
      </div>

      {/* ── current stage ───────────────────────────────────── */}
      {live ? (
        <div className="border-b-2 border-ink px-6 py-5">
          <div className="section-label">
            <span>Current stage</span>
          </div>
          <h2 className="mt-3 text-h2">{focus ? focus.spec.label : 'Starting'}</h2>
          <p className="mt-2 max-w-3xl text-lead">
            {focus?.message ?? focus?.spec.explainer ?? 'Waiting for the first event from the agent.'}
          </p>

          {focus ? (
            <p className="mt-3 max-w-3xl text-meta text-status-idle">{focus.spec.explainer}</p>
          ) : null}

          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-micro tabular text-status-idle">
            <span>Elapsed {clock(totalSeconds)}</span>
            {focus && stageSeconds !== null ? (
              <span>Stage duration {clock(stageSeconds)}</span>
            ) : null}
            {focus ? <span>Step {focus.index} of {view.total}</span> : null}
          </div>

          {retry ? (
            <div className="mt-4 border-2 border-status-warn px-4 py-3">
              <div className="flex items-center gap-2 text-label font-black uppercase tracking-widest text-status-warn">
                <Loader2 size={11} strokeWidth={3} className="animate-spin" aria-hidden />
                Retrying — attempt {retry.attempt}
              </div>
              <p className="mt-2 text-meta">
                {retryRemaining > 0
                  ? `Retrying in ${retryRemaining}s.`
                  : 'Waiting for provider response…'}
              </p>
              <p className="mt-1 text-micro text-status-idle">
                Reason: {retry.reason}. The agent waits the window the provider reported and
                retries, so no memory is silently lost.
              </p>
            </div>
          ) : stalled ? (
            <div className="mt-4 border-l-4 border-accent pl-4">
              <p className="text-meta">
                {focus?.spec.external
                  ? 'Waiting for provider response…'
                  : (focus?.spec.waiting ?? 'Waiting for the operation to report back…')}
              </p>
              <p className="mt-1 text-micro text-status-idle">
                {focus?.spec.waiting ?? 'This step reports when it finishes.'} Nothing new has
                arrived for {Math.round(sinceLastEvent)}s, and no completion time is reported, so
                none is shown.
              </p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="border-b-2 border-ink px-6 py-5">
          <StatusMark variant={TONE_VARIANT[summary.tone] ?? 'idle'} label={summary.outcome} />
          <h2 className="mt-3 text-h2">{summary.headline}</h2>
          <ul className="mt-4 flex flex-wrap gap-x-8 gap-y-2">
            {summary.facts.map((fact) => (
              <li key={fact} className="flex items-center gap-2 text-meta">
                <Check size={12} strokeWidth={3} className="shrink-0 text-status-ok" aria-hidden />
                {fact}
              </li>
            ))}
          </ul>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            {onRunSimilar ? (
              <button
                type="button"
                onClick={onRunSimilar}
                disabled={similarBusy}
                className="inline-flex items-center gap-2 border-2 border-accent bg-accent px-4 py-2.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:border-ink hover:bg-ink disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Play size={14} strokeWidth={2.5} aria-hidden />
                {similarBusy ? 'Starting' : 'Run similar incident'}
              </button>
            ) : null}
            {onViewInvestigation ? (
              <button
                type="button"
                onClick={onViewInvestigation}
                className="inline-flex items-center gap-2 border-2 border-ink bg-paper px-4 py-2.5 text-meta font-bold uppercase tracking-wide text-ink transition-colors duration-150 ease-linear hover:bg-ink hover:text-paper"
              >
                View investigation
                <ArrowRight size={14} strokeWidth={2.5} aria-hidden />
              </button>
            ) : null}
          </div>
        </div>
      )}

      {/* ── memory reuse callout ────────────────────────────── */}
      {comparabilityDone ? (
        comparable ? (
          <div className="border-b-2 border-ink bg-muted px-6 py-5">
            <div className="section-label">
              <span>Historical memory found</span>
            </div>
            <dl className="mt-3 grid gap-x-10 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
              {/* The recalled document is the previous incident's own record, which is why it can
                  be named. The judge's reference is shown beside it, not instead of it. */}
              <KV k="Previous incident" mono>
                {priorIncident ?? incidentalPrior ?? 'prior record'}
              </KV>
              <KV k="Similarity" mono>
                {similarity === null ? '—' : percent(similarity)}
              </KV>
              <KV k="Previous repair" mono>
                {priorRepair === null ? 'not recorded' : titleize(priorRepair)}
              </KV>
              <KV k="Prior reference" mono>
                {incident.comparability?.prior_incident_id ?? '—'}
              </KV>
            </dl>
            <p className="mt-3 max-w-3xl text-meta">
              Adapting the historical resolution to the current failure
              {incident.comparability?.reason ? ` — ${incident.comparability.reason}` : ''}
            </p>
          </div>
        ) : (
          <div className="border-b-2 border-ink px-6 py-5">
            <div className="section-label">
              <span className="text-status-warn">Recalled memory not applicable</span>
            </div>
            <p className="mt-3 max-w-3xl text-meta">
              {incident.comparability?.reason ??
                'The recalled incidents did not match this failure closely enough to be reused.'}{' '}
              The agent generates a fresh fix instead of forcing an old one.
            </p>
          </div>
        )
      ) : null}

      {/* ── the execution strip ─────────────────────────────── */}
      <div className="border-b-2 border-ink">
        <div className="grid grid-cols-2 gap-px bg-hair sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-11">
          {view.stages.map((stage) => (
            <StageCell key={stage.spec.key} stage={stage} now={now} />
          ))}
        </div>
      </div>

      {/* ── real intermediate results ───────────────────────── */}
      {evidenceBlocks.length > 0 ? (
        <div className="border-b-2 border-ink">
          {evidenceBlocks.map(({ stage, rows }) => {
            const Icon = STAGE_ICON[stage.spec.key] ?? Circle
            return (
              <div key={stage.spec.key} className="border-b border-hair px-6 py-5 last:border-b-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Icon size={13} strokeWidth={2.5} className="text-ink" aria-hidden />
                  <h3 className="text-label font-black uppercase tracking-widest text-ink">
                    {stage.spec.label}
                  </h3>
                  <StatusMark
                    variant={TONE_VARIANT[stageTone(stage)] ?? 'idle'}
                    label={STATE_LABEL[stage.state]}
                  />
                  {stage.durationMs !== null ? (
                    <span className="font-mono text-micro tabular text-status-idle">
                      {millis(stage.durationMs)}
                    </span>
                  ) : null}
                </div>
                <dl className="mt-3 grid gap-x-10 sm:grid-cols-2">
                  {rows.map((row, index) => (
                    <KV key={`${row.label}-${index}`} k={row.label}>
                      <span
                        className={
                          row.tone === 'ok'
                            ? 'text-status-ok'
                            : row.tone === 'warn'
                              ? 'text-status-warn'
                              : row.tone === 'bad'
                                ? 'text-status-bad'
                                : undefined
                        }
                      >
                        {row.value}
                      </span>
                    </KV>
                  ))}
                </dl>
              </div>
            )
          })}
        </div>
      ) : null}

      {/* ── activity feed ───────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 px-6 pt-4">
        <h3 className="text-label font-black uppercase tracking-widest text-status-idle">
          Activity
        </h3>
        <span className="font-mono text-micro tabular text-status-idle">
          {view.reached} step{view.reached === 1 ? '' : 's'} reported
          {startedAt ? ` · started ${clock(totalSeconds)} ago` : ''}
        </span>
      </div>
      <div className="mt-2">
        <ActivityStream
          events={events}
          height="18rem"
          emptyDetail="The agent's steps appear here the moment each one happens."
        />
      </div>
      {view.lastEventAt ? (
        <div className="border-t border-hair px-6 py-3 font-mono text-micro tabular text-status-idle">
          Last event {clock(sinceLastEvent)} ago
          {live ? ' · the panel updates the moment the next one arrives' : ''}
        </div>
      ) : null}
    </Panel>
  )
}
