import { Play, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type IncidentSummary } from '../lib/api'
import { localDateTime, relativeTime, titleize } from '../lib/format'
import { useApi } from '../lib/hooks'
import { appPath } from '../lib/site'
import { useRefreshAfter, useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import { IncidentTable } from '../components/IncidentTable'
import { Btn, Failure, Loading, Panel, SectionHeader, Tag } from '../components/primitives'

export default function Incidents() {
  const { status } = useSystem()
  const refresh = useRefreshAfter()
  const incidents = useApi<{ incidents: IncidentSummary[] }>(() => api.incidents(100), [], {
    pollMs: 15_000,
  })
  const scenarios = useApi(() => api.scenarios(), [], { pollMs: 30_000 })
  const [starting, setStarting] = useState<string | null>(null)
  const navigate = useNavigate()

  // Open the live execution panel straight away: a scenario that runs invisibly is impossible
  // to judge, and impossible to trust.
  const start = async (scenario: string) => {
    setStarting(scenario)
    try {
      const result = await api.startIncident({ scenario })
      incidents.reload()
      refresh()
      navigate(appPath(`/incidents/${result.incident.id}`))
    } finally {
      setStarting(null)
    }
  }

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Incidents"
          description="Every failure the agent has investigated, with the classification it chose and how the run ended."
        />
      </header>

      {/* ── demonstration scenarios ──────────────────────────── */}
      <section>
        <SectionHeader
          index="02."
          title="Demonstration scenarios"
          description="Deliberate failures built into the demo repository, each chosen to exercise a different part of the reasoning."
        />
        <div className="mt-5">
          {scenarios.initial ? (
            <Panel>
              <Loading label="Reading scenarios" rows={3} />
            </Panel>
          ) : scenarios.error ? (
            <Failure
              title="Could not read the demo scenarios"
              message={scenarios.error.message}
              detail={scenarios.error.detail}
              onRetry={scenarios.reload}
            />
          ) : (
            <div className="grid gap-5 lg:grid-cols-3">
              {(scenarios.data?.scenarios ?? []).map((scenario) => (
                <Panel key={scenario.key} className="flex flex-col">
                  <div className="flex items-start justify-between gap-3 p-5">
                    <div className="min-w-0">
                      <h3 className="text-meta font-black uppercase tracking-wide">{scenario.label}</h3>
                      <p className="mt-2 text-meta text-status-idle">{scenario.description}</p>
                    </div>
                    <Tag tone="neutral">{scenario.key}</Tag>
                  </div>
                  <div className="mt-auto border-t-2 border-hair px-5 py-4">
                    <div className="text-label font-black uppercase tracking-widest text-status-idle">
                      Expected behaviour
                    </div>
                    <p className="mt-1 text-micro text-ink">{scenario.expectation}</p>
                    <div className="mt-4">
                      <Btn
                        icon={Play}
                        size="sm"
                        variant="secondary"
                        onClick={() => void start(scenario.key)}
                        disabled={starting !== null || status?.running === true}
                      >
                        {starting === scenario.key ? 'Starting' : 'Run scenario'}
                      </Btn>
                    </div>
                  </div>
                </Panel>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ── recorded runs on disk ────────────────────────────── */}
      {scenarios.data && scenarios.data.runs.length > 0 ? (
        <section>
          <SectionHeader
            index="03."
            title="Recorded trajectories"
            description="Runs saved to data/runs. These are what offline replay serves, and what supplies a patch when no provider is available."
          />
          <Panel className="mt-5">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b-2 border-ink">
                    <th scope="col" className="px-4 py-2.5 text-label font-black uppercase tracking-widest text-status-idle">
                      Incident
                    </th>
                    <th scope="col" className="px-4 py-2.5 text-label font-black uppercase tracking-widest text-status-idle">
                      Classification
                    </th>
                    <th scope="col" className="px-4 py-2.5 text-label font-black uppercase tracking-widest text-status-idle">
                      Outcome
                    </th>
                    <th scope="col" className="px-4 py-2.5 text-right text-label font-black uppercase tracking-widest text-status-idle">
                      Attempts
                    </th>
                    <th scope="col" className="px-4 py-2.5 text-right text-label font-black uppercase tracking-widest text-status-idle">
                      Recorded
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.data.runs.map((run) => (
                    <tr key={run.id} className="border-b border-hair hover:bg-muted">
                      <td className="px-4 py-3">
                        <a
                          href={`/incidents/${run.id}`}
                          className="font-mono text-micro font-bold underline-offset-4 hover:text-accent hover:underline"
                        >
                          {run.id}
                        </a>
                        {run.label ? (
                          <div className="mt-0.5 text-micro text-status-idle">{run.label}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-meta">{titleize(run.error_class)}</td>
                      <td className="px-4 py-3">
                        <Tag
                          tone={
                            run.outcome === 'recovered'
                              ? 'ok'
                              : run.outcome === 'escalated'
                                ? 'warn'
                                : run.outcome
                                  ? 'bad'
                                  : 'neutral'
                          }
                        >
                          {run.outcome ?? 'incomplete'}
                        </Tag>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-meta tabular">{run.attempts}</td>
                      <td className="px-4 py-3 text-right text-micro text-status-idle" title={localDateTime(run.created_at)}>
                        {relativeTime(run.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </section>
      ) : null}

      {/* ── history ──────────────────────────────────────────── */}
      <section>
        <SectionHeader
          index="04."
          title="History"
          action={
            status ? (
              <Tag tone="neutral">
                {status.metrics.total_incidents} stored · {status.metrics.active_incidents} active
              </Tag>
            ) : null
          }
        />
        <Panel className="mt-5">
          {incidents.initial ? (
            <Loading label="Reading incident history" />
          ) : incidents.error ? (
            <Failure
              title="Could not read the incident history"
              message={incidents.error.message}
              detail={incidents.error.detail}
              onRetry={incidents.reload}
            />
          ) : (
            <IncidentTable incidents={incidents.data?.incidents ?? []} />
          )}
        </Panel>
        {!incidents.initial && !incidents.error && (incidents.data?.incidents.length ?? 0) > 0 ? (
          <p className="mt-3 flex items-center gap-2 text-micro text-status-idle">
            <TriangleAlert size={11} strokeWidth={2.5} aria-hidden />
            Recalled-memory counts are per incident and are shown on each incident's own page.
          </p>
        ) : null}
      </section>
    </Page>
  )
}
