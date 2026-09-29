import { AlertTriangle, ArrowUpRight, Play } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import {
  api,
  type Incident,
  type IncidentSummary,
  type MemoryOverview,
  type SystemStatus,
} from '../lib/api'
import { duration, errorClassNote, outcomeLabel, outcomeVariant, relativeTime, titleize } from '../lib/format'
import { useApi } from '../lib/hooks'
import { APP_PATH } from '../lib/site'
import { degradationLabel, degradationReason } from '../lib/status'
import { DiffViewer } from './DiffViewer'
import { ActionLink } from './LandingVisuals'
import { MemoryCard } from './MemoryCard'
import { TestPanel } from './TestPanel'
import { StatusMark, Tag, type Variant } from './primitives'

/**
 * Live previews of the running deployment.
 *
 * Every figure and every artefact below is read from the API at page load — the landing page
 * has no sample data of its own. When there is nothing to show, it says so and points at the
 * system, because an invented screenshot would be a claim about the product that the product
 * has not made.
 */

const MEMORY_POLL_MS = 30_000

type LiveState = 'loading' | 'ready' | 'empty' | 'unavailable'

const CHIP: Record<LiveState, { variant: Variant; label: string }> = {
  loading: { variant: 'info', label: 'Reading' },
  ready: { variant: 'ok', label: 'Live read' },
  empty: { variant: 'idle', label: 'Nothing recorded yet' },
  unavailable: { variant: 'warn', label: 'Not reachable' },
}

function Frame({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-2 border-ink bg-paper">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-ink px-5 py-3">
        <h3 className="text-label font-black uppercase tracking-widest text-ink">{title}</h3>
        {meta}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <p className="max-w-2xl text-meta text-status-idle">{children}</p>
}

// ── the instance ──────────────────────────────────────────────

/** Real counters from the running deployment. This replaces a hero mock-up. */
export function InstanceStrip() {
  const status = useApi<SystemStatus>(() => api.status(), [], { pollMs: MEMORY_POLL_MS })
  const data = status.data

  const cells = data
    ? [
        {
          label: 'Incidents recorded',
          value: String(data.metrics.total_incidents),
          note: `${data.metrics.resolved} recovered · ${data.metrics.rolled_back} rolled back · ${data.metrics.escalated} escalated`,
        },
        {
          label: 'Memories retained',
          value: String(data.memory.retains),
          note: 'Trajectories written to Hindsight',
        },
        {
          label: 'Memories recalled',
          value: String(data.memory.recalls),
          note: `${data.learning.historical_fixes_reused} repair${
            data.learning.historical_fixes_reused === 1 ? '' : 's'
          } reused a recalled incident`,
        },
        {
          label: 'Sandbox',
          value: data.sandbox_backend === 'docker' ? 'Container' : 'Workspace',
          note:
            data.sandbox_backend === 'docker'
              ? 'Docker daemon reachable'
              : data.sandbox_detail || 'No Docker daemon answered',
        },
      ]
    : []

  const instanceNote = data
    ? data.healthy
      ? (data.notes[0] ?? 'Every dependency answered.')
      : degradationReason(data)
    : ''

  return (
    <div className="border-2 border-ink bg-paper">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-ink px-5 py-3">
        <h3 className="text-label font-black uppercase tracking-widest text-ink">
          Live from the running instance
        </h3>
        {status.initial ? (
          <StatusMark variant="info" label="Connecting" />
        ) : data ? (
          <StatusMark
            variant={data.healthy ? 'ok' : 'warn'}
            label={data.healthy ? 'Operational' : `Degraded · ${degradationLabel(data)}`}
          />
        ) : (
          <StatusMark variant="warn" label="Not answering" />
        )}
      </div>

      {status.initial ? (
        <p role="status" className="px-5 py-5 text-meta text-status-idle">
          Reading the running instance…
        </p>
      ) : !data ? (
        <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-5">
          <Note>
            This page could not read the API, so it shows no figures at all. The dashboard
            reports the reason in full.
          </Note>
          <ActionLink to={APP_PATH} variant="secondary" icon={ArrowUpRight}>
            Open the system
          </ActionLink>
        </div>
      ) : (
        <>
          <ul className="grid grid-cols-1 gap-px bg-hair sm:grid-cols-2 lg:grid-cols-4">
            {cells.map((cell) => (
              <li key={cell.label} className="bg-paper px-5 py-4">
                <div className="text-label font-black uppercase tracking-widest text-status-idle">
                  {cell.label}
                </div>
                <div className="mt-2 text-h2 font-black tabular">{cell.value}</div>
                <p className="mt-1.5 line-clamp-2 text-micro text-status-idle" title={cell.note}>
                  {cell.note}
                </p>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-2 border-t-2 border-hair px-5 py-3">
            <p className="font-mono text-micro text-status-idle">
              v{data.version}
              {data.hindsight_version ? ` · Hindsight ${data.hindsight_version}` : ''}
            </p>
            <p className="max-w-2xl text-micro text-status-idle">{instanceNote}</p>
          </div>
        </>
      )}
    </div>
  )
}

// ── memory ────────────────────────────────────────────────────

export function MemoryPreview() {
  const memory = useApi<MemoryOverview>(() => api.memory(), [], { pollMs: MEMORY_POLL_MS })
  const overview = memory.data
  const banks = Object.values(overview?.banks ?? {})
  const bank = banks.find((entry) => entry.memories.length > 0) ?? banks[0] ?? null
  const shown = bank?.memories.slice(0, 2) ?? []
  const counters = overview?.counters ?? null

  const state: LiveState = memory.initial
    ? 'loading'
    : !overview || !overview.available
      ? 'unavailable'
      : shown.length > 0
        ? 'ready'
        : 'empty'

  return (
    <Frame
      title={bank ? `Memory · ${bank.bank_id}` : 'Memory'}
      meta={<StatusMark variant={CHIP[state].variant} label={CHIP[state].label} />}
    >
      {state === 'loading' ? (
        <p role="status" className="text-meta text-status-idle">
          Reading the memory banks…
        </p>
      ) : null}

      {state === 'unavailable' ? (
        <div className="space-y-4">
          <Note>
            Hindsight is not reachable from this page, so nothing is shown here rather than
            something invented. {memory.error?.message ?? overview?.detail ?? ''}
          </Note>
          <ActionLink to={`${APP_PATH}/memory`} variant="secondary" icon={ArrowUpRight}>
            Inspect memory
          </ActionLink>
        </div>
      ) : null}

      {state === 'empty' ? (
        <div className="space-y-4">
          <p className="max-w-2xl text-meta text-ink">
            Hindsight answered, and this deployment has not stored anything yet.
          </p>
          <Note>
            Memory is written when an incident reaches a terminal state — recovered, rolled back
            or escalated. The first run has nothing to recall and everything to teach, which is
            the point of the section above.
          </Note>
          <ActionLink to={APP_PATH} icon={Play}>
            Run the first incident
          </ActionLink>
        </div>
      ) : null}

      {state === 'ready' ? (
        <>
          {counters ? (
            <dl className="mb-5 grid grid-cols-2 gap-px bg-hair sm:grid-cols-4">
              {[
                { label: 'Retained', value: counters.retains },
                { label: 'Recalled', value: counters.recalls },
                { label: 'Reflects', value: counters.reflects },
                { label: 'Failed', value: counters.failures },
              ].map((item) => (
                <div key={item.label} className="bg-paper px-4 py-3">
                  <dt className="text-label font-black uppercase tracking-widest text-status-idle">
                    {item.label}
                  </dt>
                  <dd className="mt-1 font-mono text-meta font-bold tabular">{item.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          <div className="space-y-4">
            {shown.map((entry) => (
              <MemoryCard key={entry.memory_id} memory={entry} />
            ))}
          </div>
          <p className="mt-5 text-micro text-status-idle">
            {bank && bank.memories.length > shown.length
              ? `Showing 2 of ${bank.memories.length} memories in this bank.`
              : `Showing ${shown.length} of ${bank?.memories.length ?? 0} memories in this bank.`}
          </p>
        </>
      ) : null}
    </Frame>
  )
}

// ── the product, rendered from a real incident ────────────────

export function ProductPreview() {
  const list = useApi<{ incidents: IncidentSummary[] }>(() => api.incidents(5), [], {
    pollMs: MEMORY_POLL_MS,
  })
  const latestId = list.data?.incidents[0]?.id ?? null
  const incident = useApi<Incident>(() => api.incident(latestId as string), [latestId], {
    enabled: Boolean(latestId),
  })
  const record = incident.data

  if (list.initial || (latestId !== null && incident.initial)) {
    return (
      <Frame title="Latest incident" meta={<StatusMark variant="info" label="Reading" />}>
        <p role="status" className="text-meta text-status-idle">
          Reading the incident record…
        </p>
      </Frame>
    )
  }

  if (!latestId || !record) {
    return (
      <Frame
        title="Latest incident"
        meta={
          <StatusMark
            variant={list.error ? 'warn' : 'idle'}
            label={list.error ? 'Not reachable' : 'Nothing recorded yet'}
          />
        }
      >
        <div className="space-y-4">
          <Note>
            {list.error
              ? 'This page could not read the incident history, so no record is shown.'
              : 'No incident has been recorded on this deployment yet. The dashboard will show the full investigation here once one has run.'}
          </Note>
          <ActionLink to={APP_PATH} icon={Play}>
            Open the system
          </ActionLink>
        </div>
      </Frame>
    )
  }

  const attempts = [...record.attempts].reverse()
  const patchDiff =
    attempts.find((attempt) => attempt.patch?.diff)?.patch?.diff ?? null
  const sandbox = attempts.map((attempt) => attempt.sandbox).find((entry) => entry?.test_report) ?? null
  const recalled = record.memory_refs[0] ?? null
  const recovered = record.outcome === 'recovered'

  return (
    <div className="grid grid-cols-1 gap-6 lg:gap-8 lg:grid-cols-12">
      <div className="lg:col-span-7">
        <Frame
          title={`Incident ${record.id}`}
          meta={
            <span className="flex flex-wrap items-center gap-2">
              {record.run_mode && record.run_mode !== 'live' ? (
                <Tag tone="neutral">{record.run_mode}</Tag>
              ) : null}
              <StatusMark variant={outcomeVariant(record.outcome)} label={outcomeLabel(record.outcome)} />
            </span>
          }
        >
          <h3 className="text-h3">{titleize(record.classification?.error_class) || 'Unclassified failure'}</h3>
          {errorClassNote(record.classification?.error_class) ? (
            <p className="mt-1.5 text-meta text-status-idle">
              {errorClassNote(record.classification?.error_class)}
            </p>
          ) : null}
          <p className="mt-3 line-clamp-3 text-meta text-ink">{record.error}</p>

          <dl className="mt-5 grid grid-cols-2 gap-px bg-hair sm:grid-cols-4">
            {[
              { label: 'Attempts', value: String(record.metrics.attempts_used) },
              { label: 'Duration', value: duration(record.metrics.duration_s) },
              { label: 'Memories recalled', value: String(record.metrics.memories_recalled) },
              { label: 'Memories reused', value: String(record.metrics.memories_reused) },
            ].map((item) => (
              <div key={item.label} className="bg-paper px-3 py-2.5">
                <dt className="text-label font-black uppercase tracking-widest text-status-idle">
                  {item.label}
                </dt>
                <dd className="mt-1 font-mono text-meta font-bold tabular">{item.value}</dd>
              </div>
            ))}
          </dl>

          {patchDiff ? (
            <div className="mt-5">
              <DiffViewer
                diff={patchDiff}
                label={recovered ? 'Verified repair' : 'Proposed repair'}
                maxHeight="18rem"
              />
            </div>
          ) : (
            <p className="mt-5 flex items-start gap-2 border-l-2 border-status-warn pl-3 text-micro text-status-warn">
              <AlertTriangle size={13} strokeWidth={2.5} aria-hidden className="mt-0.5 shrink-0" />
              <span>
                No patch was generated for this incident.
                {record.escalation_reason ? ` ${record.escalation_reason}` : ''}
              </span>
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-micro text-status-idle">
              Recorded {relativeTime(record.created_at)} · commit {record.commit_sha.slice(0, 8)}
            </p>
            <Link
              to={`${APP_PATH}/incidents/${record.id}`}
              className="inline-flex items-center gap-1.5 text-label font-bold uppercase tracking-widest text-ink transition-colors duration-150 ease-linear hover:text-accent"
            >
              Open this incident
              <ArrowUpRight size={12} strokeWidth={3} aria-hidden />
            </Link>
          </div>
        </Frame>
      </div>

      <div className="space-y-6 lg:col-span-5 lg:space-y-8">
        <Frame
          title="Sandbox verification"
          meta={sandbox ? <Tag tone="neutral">{sandbox.backend}</Tag> : undefined}
        >
          {sandbox ? (
            <div className="space-y-4">
              <TestPanel title="Reproduce the failure (unpatched)" report={sandbox.reproduce_report} />
              <TestPanel title="Verify the fix (targeted)" report={sandbox.test_report} />
            </div>
          ) : (
            <Note>No sandbox run is recorded for this incident.</Note>
          )}
        </Frame>

        <Frame
          title="Memory recall"
          meta={<Tag tone={recalled ? 'accent' : 'neutral'}>{record.memory_refs.length} retrieved</Tag>}
        >
          {recalled ? (
            <MemoryCard
              memory={recalled}
              against={{
                error_class: record.classification?.error_class ?? null,
                repository: record.repository,
              }}
            />
          ) : (
            <Note>
              Nothing comparable was in memory when this incident ran, so the agent started from
              zero — and wrote this trajectory back for the next occurrence.
            </Note>
          )}
        </Frame>
      </div>
    </div>
  )
}
