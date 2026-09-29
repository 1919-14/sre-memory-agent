import { ArrowLeft, RefreshCw, ShieldAlert, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, type ExecutionEvent, type Incident } from '../lib/api'
import {
  duration,
  errorClassNote,
  localDateTime,
  outcomeLabel,
  outcomeVariant,
  shortSha,
  titleize,
} from '../lib/format'
import { useApi } from '../lib/hooks'
import { scenarioOf } from '../lib/run'
import { appPath } from '../lib/site'
import { useRefreshAfter, useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import { ActivityStream } from '../components/ActivityStream'
import { LiveRunPanel } from '../components/LiveRunPanel'
import { IncidentTimeline } from '../components/Timeline'
import {
  Btn,
  CopyButton,
  Failure,
  KV,
  Loading,
  Metric,
  Panel,
  Rule,
  SectionHeader,
  StatusMark,
  Tag,
} from '../components/primitives'

/** Statuses that mean the agent deliberately stopped and is waiting for a human. */
const AWAITING_APPROVAL = new Set(['AWAITING_APPROVAL', 'ROLLBACK_REQUIRED', 'NEEDS_APPROVAL'])

function mergeEvents(fetched: ExecutionEvent[], live: ExecutionEvent[]): ExecutionEvent[] {
  const byId = new Map<string, ExecutionEvent>()
  for (const event of [...fetched, ...live]) {
    if (!byId.has(event.id)) byId.set(event.id, event)
  }
  return [...byId.values()].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
}

export default function IncidentDetail() {
  const { incidentId = '' } = useParams()
  const { stream, status } = useSystem()
  const refresh = useRefreshAfter()
  const navigate = useNavigate()
  const incident = useApi<Incident>(() => api.incident(incidentId), [incidentId], {
    // Poll faster while a run is in flight so the panel's derived state stays current even if
    // the stream is reconnecting.
    pollMs: 4000,
  })
  const events = useApi<{ events: ExecutionEvent[] }>(() => api.events(incidentId), [incidentId])
  const [approving, setApproving] = useState(false)
  const [similarBusy, setSimilarBusy] = useState(false)

  const data = incident.data
  const liveEvents = stream.forIncident(incidentId)
  const allEvents = useMemo(
    () => mergeEvents(events.data?.events ?? [], liveEvents),
    [events.data, liveEvents],
  )

  // The live run panel is shown for the run the operator started, and stays up afterwards so the
  // finished run can be read without the panel disappearing mid-story. It is not shown for
  // incidents reopened from history, where the timeline is the right view.
  const isActiveRun = status?.active_incident_id === incidentId
  const looksLive = Boolean(
    data &&
      !data.outcome &&
      Date.now() - new Date(data.created_at).getTime() < 5 * 60 * 1000,
  )
  const [watching, setWatching] = useState(false)
  useEffect(() => {
    if (isActiveRun || looksLive) setWatching(true)
  }, [isActiveRun, looksLive])

  const approve = async () => {
    setApproving(true)
    try {
      await api.approveRollback(incidentId)
      incident.reload()
      refresh()
    } finally {
      setApproving(false)
    }
  }

  const runSimilar = async () => {
    setSimilarBusy(true)
    try {
      const result = await api.startIncident({
        scenario: scenarioOf(data?.branch) ?? 'concurrency',
      })
      // Clear the old document first: the panel is keyed to one incident, and showing the
      // finished run under the new id for a frame would misattribute it.
      incident.setData(null)
      refresh()
      navigate(appPath(`/incidents/${result.incident.id}`))
    } catch {
      // The status strip reports backend errors; a refused start needs no second banner.
    } finally {
      setSimilarBusy(false)
    }
  }

  if (incident.initial || !data) {
    return (
      <Page>
        <Loading label={`Loading incident ${incidentId}`} rows={8} />
      </Page>
    )
  }

  if (incident.error) {
    const missing = incident.error.status === 404
    return (
      <Page className="space-y-8">
        <Link
          to={appPath('/incidents')}
          className="inline-flex items-center gap-2 text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent"
        >
          <ArrowLeft size={12} strokeWidth={3} aria-hidden />
          All incidents
        </Link>
        {missing ? (
          <Failure
            warning
            title="Incident not recorded"
            message={`No incident with the id ${incidentId} exists in the operational store or the recorded trajectories.`}
            detail={incident.error.detail}
          />
        ) : (
          <Failure
            title="Could not load this incident"
            message={incident.error.message}
            detail={incident.error.detail}
            onRetry={incident.reload}
          />
        )}
      </Page>
    )
  }

  const classification = data.classification
  const awaiting = AWAITING_APPROVAL.has(String(data.status))

  return (
    <Page className="space-y-10">
      {/* ── header ───────────────────────────────────────────── */}
      <header>
        <Link
          to={appPath('/incidents')}
          className="inline-flex items-center gap-2 text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent"
        >
          <ArrowLeft size={12} strokeWidth={3} aria-hidden />
          All incidents
        </Link>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <StatusMark variant={outcomeVariant(data.outcome)} label={outcomeLabel(data.outcome)} />
          <span className="font-mono text-meta text-status-idle">{data.id}</span>
          <Tag tone={data.run_mode === 'live' ? 'ok' : 'neutral'}>{data.run_mode}</Tag>
          {data.simulated ? <Tag tone="warn">simulated</Tag> : null}
          {data.degraded ? <Tag tone="warn">degraded</Tag> : null}
          <CopyButton value={data.id} label="Incident id" />
        </div>

        <h1 className="mt-5 max-w-4xl text-h1">
          {classification ? titleize(classification.error_class) : 'Unclassified failure'}
        </h1>
        {classification ? (
          <p className="mt-3 max-w-3xl text-lead text-status-idle">
            {errorClassNote(classification.error_class)} · classified with{' '}
            {Math.round(classification.confidence * 100)}% confidence from {classification.source}
          </p>
        ) : null}

        {data.error ? (
          <p className="mt-5 max-w-3xl border-l-4 border-ink pl-4 text-meta">{data.error}</p>
        ) : null}
      </header>

      {/* ── live execution ──────────────────────────────────── */}
      {watching ? (
        <LiveRunPanel
          incident={data}
          events={allEvents}
          live={!data.outcome}
          onRunSimilar={() => void runSimilar()}
          similarBusy={similarBusy}
          onViewInvestigation={() => {
            document.getElementById('investigation')?.scrollIntoView({ block: 'start' })
          }}
        />
      ) : null}

      {/* ── provenance + key facts ───────────────────────────── */}
      <div className="grid gap-8 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-px bg-hair lg:grid-cols-4">
            <Metric value={data.metrics.attempts_used} label="Attempts executed" />
            <Metric value={data.metrics.memories_recalled} label="Memories recalled" />
            <Metric
              value={data.metrics.memories_reused}
              label="Fixes reused"
              tone={data.metrics.memories_reused > 0 ? 'ok' : 'ink'}
            />
            <Metric value={duration(data.metrics.duration_s)} label="Duration" />
          </div>
          <Rule />
          <dl className="grid gap-x-8 px-6 py-4 sm:grid-cols-2">
            <KV k="Repository" mono>
              {data.repository}
            </KV>
            <KV k="Branch" mono>
              {data.branch || '—'}
            </KV>
            <KV k="Commit" mono>
              {shortSha(data.commit_sha)}
            </KV>
            <KV k="Last known good" mono>
              {shortSha(data.previous_good_commit)}
            </KV>
            <KV k="Trigger" mono>
              {data.trigger}
            </KV>
            <KV k="Created" mono>
              {localDateTime(data.created_at)}
            </KV>
            <KV k="Resolved" mono>
              {localDateTime(data.resolved_at)}
            </KV>
            <KV k="Rollback target" mono>
              {data.rollback_commit ? shortSha(data.rollback_commit) : '—'}
            </KV>
          </dl>
        </Panel>

        <div className="space-y-5">
          {data.root_cause ? (
            <Panel className="p-5">
              <div className="text-label font-black uppercase tracking-widest text-accent">
                Root cause
              </div>
              <p className="mt-2 text-meta">{data.root_cause}</p>
            </Panel>
          ) : null}

          {data.verification ? (
            <Panel className="p-5">
              <div className="text-label font-black uppercase tracking-widest text-status-ok">
                Verification
              </div>
              <p className="mt-2 text-meta">{data.verification}</p>
            </Panel>
          ) : null}

          {data.final_resolution ? (
            <Panel className="p-5">
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Resolution
              </div>
              <p className="mt-2 text-meta">{data.final_resolution}</p>
            </Panel>
          ) : null}

          {data.escalation_reason ? (
            <Panel className="border-status-warn p-5">
              <div className="flex items-center gap-2 text-label font-black uppercase tracking-widest text-status-warn">
                <ShieldAlert size={13} strokeWidth={2.5} aria-hidden />
                Escalated to a human
              </div>
              <p className="mt-2 text-meta">{data.escalation_reason}</p>
            </Panel>
          ) : null}

          {awaiting ? (
            <Panel className="border-accent p-5">
              <div className="text-label font-black uppercase tracking-widest text-accent">
                Human approval required
              </div>
              <p className="mt-2 text-meta">
                The agent has stopped and will not proceed without an explicit decision.
              </p>
              <div className="mt-4">
                <Btn variant="accent" onClick={() => void approve()} disabled={approving}>
                  {approving ? 'Approving' : 'Approve rollback'}
                </Btn>
              </div>
            </Panel>
          ) : null}

          {data.rejected_memories.length > 0 ? (
            <Panel className="p-5">
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Memories considered and rejected
              </div>
              <ul className="mt-2 space-y-1.5">
                {data.rejected_memories.map((memory) => (
                  <li key={memory.memory_id} className="text-micro text-status-idle">
                    {memory.text}
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>

      {data.degraded && data.warnings.length > 0 ? (
        <Failure
          warning
          title="This run was degraded"
          message={data.warnings[0]}
          detail={data.warnings.join('\n\n')}
          onRetry={incident.reload}
          retryLabel="Re-read"
        />
      ) : null}

      {/* ── the investigation ────────────────────────────────── */}
      <section id="investigation" className="scroll-mt-20">
        <SectionHeader
          index="02."
          title="Investigation"
          description="Each step the agent took, in order, with the evidence behind it. Open any step to see the underlying data."
          action={
            <Btn icon={RefreshCw} size="sm" variant="ghost" onClick={incident.reload}>
              Refresh
            </Btn>
          }
        />
        <div className="mt-8">
          <IncidentTimeline incident={data} events={allEvents} />
        </div>
      </section>

      {/* ── event log + raw payload ──────────────────────────── */}
      <div className="grid gap-8 xl:grid-cols-2">
        <section>
          <SectionHeader index="03." title="Event log" />
          <Panel className="mt-5">
            {events.error ? (
              <Failure
                title="Could not read the event log"
                message={events.error.message}
                detail={events.error.detail}
                onRetry={events.reload}
              />
            ) : (
              <ActivityStream
                events={allEvents}
                height="22rem"
                emptyDetail="This incident has no recorded events."
              />
            )}
          </Panel>
        </section>

        <section>
          <SectionHeader index="04." title="Recorded payload" />
          <Panel className="mt-5">
            <details>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-label font-black uppercase tracking-widest text-status-idle transition-colors hover:text-accent">
                <span className="flex items-center gap-2">
                  <TriangleAlert size={12} strokeWidth={2.5} aria-hidden />
                  Full incident document
                </span>
                <CopyButton value={JSON.stringify(data, null, 2)} label="Incident JSON" />
              </summary>
              <pre className="code-surface max-h-[22rem] overflow-auto border-t-2 border-ink p-4 text-micro">
                {JSON.stringify(data, null, 2)}
              </pre>
            </details>
          </Panel>
        </section>
      </div>
    </Page>
  )
}
