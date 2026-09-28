import {
  ArrowRight,
  BrainCircuit,
  CircleCheck,
  CircleX,
  Play,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, type IncidentSummary } from '../lib/api'
import { errorClassNote, percent, relativeTime, titleize } from '../lib/format'
import { useApi } from '../lib/hooks'
import { useRefreshAfter, useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import { ActivityStream } from '../components/ActivityStream'
import {
  Btn,
  Empty,
  Failure,
  Loading,
  Metric,
  Panel,
  Rule,
  SectionHeader,
  StatusMark,
  Tag,
  type Variant,
} from '../components/primitives'

/** The five things an operator checks first. */
function systemRows(status: ReturnType<typeof useSystem>['status']) {
  if (!status) return []
  return [
    {
      label: 'Agent',
      variant: (status.healthy ? 'ok' : 'warn') as Variant,
      value: status.healthy ? 'Operational' : 'Degraded',
      // When degraded, say why. Reporting "Idle, ready for work" next to a DEGRADED badge
      // contradicts itself and tells the operator nothing.
      note: status.running
        ? 'An incident is running now'
        : (status.warnings[0] ?? 'Idle, ready for work'),
    },
    {
      label: 'Hindsight memory',
      variant: (status.hindsight_ready ? 'ok' : 'warn') as Variant,
      value: status.hindsight_ready ? 'Connected' : 'Unavailable',
      note: status.hindsight_ready
        ? `${status.hindsight_version || 'version unknown'} · ${status.banks.incident}`
        : status.hindsight_detail,
    },
    {
      label: 'LLM provider',
      variant: (status.llm_ready ? 'ok' : 'bad') as Variant,
      value: status.llm_ready ? 'Connected' : 'Not configured',
      note: status.llm_ready ? 'Classification, repair and review' : 'Set GROQ_API_KEY to enable reasoning',
    },
    {
      label: 'Sandbox',
      variant: (status.sandbox_backend === 'docker' ? 'ok' : 'warn') as Variant,
      value: status.sandbox_backend === 'docker' ? 'Isolated' : 'Local fallback',
      note:
        status.sandbox_backend === 'docker'
          ? 'Generated code runs in a container with no network and resource caps'
          : 'Docker is unavailable or its sandbox image is missing, so generated code runs in a temporary workspace instead of a container',
    },
    {
      label: 'Repository',
      variant: (status.repo_present ? 'ok' : 'bad') as Variant,
      value: status.repo_present ? 'Present' : 'Missing',
      note: status.repo_present
        ? `${status.repo_path.split(/[\\/]/).pop()} @ ${status.repo_commit.slice(0, 8)}`
        : status.repo_path,
    },
  ]
}

function HeroIncident({ incident }: { incident: IncidentSummary }) {
  const variant = (
    incident.outcome === 'recovered'
      ? 'ok'
      : incident.outcome === 'escalated'
        ? 'warn'
        : incident.outcome
          ? 'bad'
          : 'info'
  ) as Variant

  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-col gap-6 p-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <StatusMark variant={variant} label={(incident.outcome ?? 'in progress').toUpperCase()} />
            <span className="font-mono text-micro text-status-idle">{incident.id}</span>
            {incident.run_mode ? <Tag tone="neutral">{incident.run_mode}</Tag> : null}
            {incident.source === 'recorded' ? <Tag tone="neutral">recorded</Tag> : null}
          </div>
          <h3 className="mt-4 max-w-2xl text-h2">
            {titleize(incident.error_class) || 'Unclassified failure'}
          </h3>
          {errorClassNote(incident.error_class) ? (
            <p className="mt-2 text-meta text-status-idle">{errorClassNote(incident.error_class)}</p>
          ) : null}
          <p className="mt-3 line-clamp-2 max-w-2xl text-meta text-ink">
            {incident.error || 'No error summary was recorded for this incident.'}
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-start gap-3">
          <div className="flex items-center gap-6">
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Attempts
              </div>
              <div className="text-h2 font-black tabular">{incident.attempts ?? 0}</div>
            </div>
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Recorded
              </div>
              <div className="text-meta">{relativeTime(incident.created_at)}</div>
            </div>
          </div>
          <Link
            to={`/incidents/${incident.id}`}
            className="inline-flex items-center gap-2 border-2 border-ink bg-ink px-4 py-2.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:border-accent hover:bg-accent"
          >
            Open investigation
            <ArrowRight size={14} strokeWidth={2.5} aria-hidden />
          </Link>
        </div>
      </div>
    </Panel>
  )
}

export default function Overview() {
  const { status, stream } = useSystem()
  const refresh = useRefreshAfter()
  const navigate = useNavigate()
  const incidents = useApi<{ incidents: IncidentSummary[] }>(() => api.incidents(25), [], {
    pollMs: 15_000,
  })
  const [starting, setStarting] = useState<string | null>(null)

  const list = incidents.data?.incidents ?? []
  const latest = list[0] ?? null
  const activeIncident = list.find((incident) => incident.id === status?.active_incident_id) ?? null
  const metrics = status?.metrics
  const learning = status?.learning

  /**
   * Start a scenario and open its live execution panel.
   *
   * Navigating immediately matters: the panel is where the run becomes observable, and a
   * button that only flips to a spinner tells the operator nothing about what the agent is
   * doing.
   */
  const start = async (scenario: string) => {
    setStarting(scenario)
    try {
      const result = await api.startIncident({ scenario })
      incidents.reload()
      refresh()
      navigate(`/incidents/${result.incident.id}`)
    } finally {
      setStarting(null)
    }
  }

  return (
    <Page className="space-y-12">
      {/* ── header ───────────────────────────────────────────── */}
      <header>
        <SectionHeader
          index="01."
          title="Overview"
          description="The state of the agent, the repository it watches, and what memory has bought it so far."
        />
      </header>

      {/* ── system + activity ────────────────────────────────── */}
      <div className="grid gap-8 xl:grid-cols-12">
        <section className="xl:col-span-7">
          <SectionHeader index="02." title="System status" />
          <Panel className="mt-5">
            <div className="grid grid-cols-1 gap-px bg-hair sm:grid-cols-2 lg:grid-cols-5">
              {systemRows(status).map((row) => (
                <div key={row.label} className="bg-paper px-5 py-4">
                  <div className="text-label font-black uppercase tracking-widest text-status-idle">
                    {row.label}
                  </div>
                  <div className="mt-2">
                    <StatusMark variant={row.variant} label={row.value} />
                  </div>
                  <p className="mt-2 line-clamp-3 text-micro text-status-idle" title={row.note}>
                    {row.note}
                  </p>
                </div>
              ))}
            </div>
          </Panel>

          {status && status.warnings.length > 0 ? (
            <div className="mt-5">
              <Failure
                warning
                title="Operating in degraded mode"
                message={status.warnings[0]}
                detail={status.warnings.join('\n\n')}
                onRetry={refresh}
                retryLabel="Re-check"
              />
            </div>
          ) : null}

          {/* Healthy facts, deliberately not styled as a problem. */}
          {status && status.warnings.length === 0 && status.notes.length > 0 ? (
            <Panel className="mt-5">
              <ul className="divide-y divide-hair">
                {status.notes.map((note) => (
                  <li key={note} className="flex items-start gap-3 px-5 py-3">
                    <CircleCheck
                      size={13}
                      strokeWidth={2.5}
                      className="mt-0.5 shrink-0 text-status-ok"
                      aria-hidden
                    />
                    <span className="text-micro text-status-idle">{note}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}

          {/* demo entry point */}
          <Panel className="mt-5">
            <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-label font-black uppercase tracking-widest text-accent">
                  Demonstration
                </div>
                <p className="mt-1.5 max-w-lg text-meta text-status-idle">
                  Run the connection-pool scenario, then run the same failure again: the second
                  run recalls the first one and adapts the repair it already proved.
                </p>
              </div>
              {status?.running && status.active_incident_id ? (
                <Link
                  to={`/incidents/${status.active_incident_id}`}
                  className="inline-flex shrink-0 items-center gap-2 border-2 border-accent bg-accent px-4 py-2.5 text-meta font-bold uppercase tracking-wide text-paper transition-colors duration-150 ease-linear hover:border-ink hover:bg-ink"
                >
                  <span aria-hidden className="h-2 w-2 animate-pulse-slow bg-paper" />
                  Follow the running incident
                  <ArrowRight size={14} strokeWidth={2.5} aria-hidden />
                </Link>
              ) : (
                <div className="flex flex-wrap gap-3">
                  <Btn
                    icon={Play}
                    variant="primary"
                    onClick={() => void start('concurrency')}
                    disabled={starting !== null}
                  >
                    {starting === 'concurrency' ? 'Starting' : 'Run incident'}
                  </Btn>
                  <Btn
                    icon={RefreshCw}
                    variant="secondary"
                    onClick={() => void start('concurrency')}
                    disabled={starting !== null}
                    title="Run the same failure again, so the agent recalls the first repair"
                  >
                    {starting === 'concurrency' ? 'Starting' : 'Run similar incident'}
                  </Btn>
                </div>
              )}
            </div>
          </Panel>
        </section>

        <section className="xl:col-span-5">
          <SectionHeader
            index="03."
            title="Live activity"
            action={
              <StatusMark
                variant={stream.state === 'live' ? 'ok' : stream.state === 'closed' ? 'idle' : 'info'}
                label={stream.state}
              />
            }
          />
          <Panel className="mt-5">
            <ActivityStream
              events={stream.events.slice(-60)}
              height="26rem"
              emptyDetail="Start an incident, or run one from the CLI, and the agent's steps stream here as they happen."
            />
          </Panel>
        </section>
      </div>

      {/* ── metrics ──────────────────────────────────────────── */}
      <section>
        <SectionHeader
          index="04."
          title="Recorded performance"
          description="Every figure is computed from stored incidents, not estimated."
        />
        {metrics ? (
          <Panel className="mt-5">
            <div className="grid grid-cols-2 gap-px bg-hair lg:grid-cols-4">
              <Metric value={metrics.total_incidents} label="Incidents" />
              <Metric value={metrics.resolved} label="Recovered" tone="ok" />
              <Metric value={metrics.rolled_back} label="Rolled back" tone={metrics.rolled_back > 0 ? 'bad' : 'idle'} />
              <Metric value={metrics.escalated} label="Escalated" tone={metrics.escalated > 0 ? 'warn' : 'idle'} />
              <Metric
                value={learning ? percent(learning.repair_success_rate, { from: 'percent' }) : '—'}
                label="Repair success"
                tone="ok"
              />
              <Metric
                value={learning ? learning.avg_attempts.toFixed(1) : '—'}
                label="Avg attempts"
                note="Lower over time means memory is working"
              />
              <Metric
                value={learning?.memories_recalled ?? 0}
                label="Memories recalled"
              />
              <Metric
                value={learning?.historical_fixes_reused ?? 0}
                label="Fixes reused"
                tone="ok"
                note="Repairs adapted from a recalled incident"
              />
            </div>
          </Panel>
        ) : (
          <Panel className="mt-5">
            <Loading label="Reading metrics" rows={3} />
          </Panel>
        )}
      </section>

      {/* ── latest incident ──────────────────────────────────── */}
      <section>
        <SectionHeader
          index="05."
          title="Latest incident"
          action={
            <Link
              to="/incidents"
              className="inline-flex items-center gap-1.5 text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent"
            >
              All incidents
              <ArrowRight size={12} strokeWidth={3} aria-hidden />
            </Link>
          }
        />

        <div className="mt-5">
          {incidents.initial ? (
            <Panel>
              <Loading label="Reading incident history" />
            </Panel>
          ) : incidents.error ? (
            <Failure
              title="Could not read the incident history"
              message={incidents.error.message}
              detail={incidents.error.detail}
              onRetry={incidents.reload}
            />
          ) : latest ? (
            <HeroIncident incident={latest} />
          ) : (
            <Panel>
              <Empty
                icon={TriangleAlert}
                title="No incidents yet"
                detail="Nothing has been investigated. Run the demonstration incident above to see the full cycle, including what the agent remembers afterwards."
              />
            </Panel>
          )}
        </div>
      </section>

      {/* ── what the agent knows ─────────────────────────────── */}
      <section>
        <SectionHeader index="06." title="What memory is doing" />
        <Panel className="mt-5">
          <div className="grid gap-px bg-hair lg:grid-cols-3">
            <div className="bg-paper p-6">
              <BrainCircuit size={18} strokeWidth={2.5} className="text-accent" aria-hidden />
              <h3 className="mt-3 text-meta font-black uppercase tracking-widest">Retained</h3>
              <p className="mt-2 text-meta text-status-idle">
                {status?.memory.retains ?? 0} write{status?.memory.retains === 1 ? '' : 's'} to Hindsight.
                Every incident is stored with its failed attempts, not just the fix that worked.
              </p>
            </div>
            <div className="bg-paper p-6">
              <CircleCheck size={18} strokeWidth={2.5} className="text-status-ok" aria-hidden />
              <h3 className="mt-3 text-meta font-black uppercase tracking-widest">Recalled</h3>
              <p className="mt-2 text-meta text-status-idle">
                {status?.memory.recalls ?? 0} read{status?.memory.recalls === 1 ? '' : 's'}.
                {learning
                  ? ` ${learning.failed_approaches_avoided} approach${learning.failed_approaches_avoided === 1 ? '' : 'es'} previously shown to fail were avoided.`
                  : ''}
              </p>
            </div>
            <div className="bg-paper p-6">
              <ShieldCheck size={18} strokeWidth={2.5} className="text-ink" aria-hidden />
              <h3 className="mt-3 text-meta font-black uppercase tracking-widest">Memory defense</h3>
              <p className="mt-2 text-meta text-status-idle">{status?.memory_defense || 'Not reported'}</p>
            </div>
          </div>
          <Rule />
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4">
            <p className="text-micro text-status-idle">
              {status?.memory.failures
                ? `${status.memory.failures} memory operation${status.memory.failures === 1 ? '' : 's'} failed. Failures are surfaced, never hidden.`
                : 'No memory operations have failed.'}
            </p>
            <Link
              to="/memory"
              className="inline-flex items-center gap-1.5 text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent"
            >
              Inspect memory
              <ArrowRight size={12} strokeWidth={3} aria-hidden />
            </Link>
          </div>
        </Panel>
      </section>

      {/* per-incident continuity, only when a run is in flight */}
      {status?.active_incident_id ? (
        <section>
          <Panel className="border-accent">
            <div className="flex flex-wrap items-center justify-between gap-4 p-5">
              <div className="flex items-center gap-3">
                <CircleX size={16} strokeWidth={2.5} className="text-accent" aria-hidden />
                <div>
                  <div className="text-meta font-bold">
                    Incident {status.active_incident_id} is running
                  </div>
                  <p className="text-micro text-status-idle">
                    Started {relativeTime(activeIncident?.created_at ?? null)} — follow it in the
                    live activity panel.
                  </p>
                </div>
              </div>
              <Link
                to={`/incidents/${status.active_incident_id}`}
                className="inline-flex items-center gap-2 border-2 border-accent px-4 py-2 text-meta font-bold uppercase tracking-wide text-accent transition-colors hover:bg-accent hover:text-paper"
              >
                Follow
                <ArrowRight size={13} strokeWidth={2.5} aria-hidden />
              </Link>
            </div>
          </Panel>
        </section>
      ) : null}
    </Page>
  )
}
