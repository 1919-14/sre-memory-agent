import { TrendingUp } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { api, type IncidentSummary } from '../lib/api'
import { percent, relativeTime, titleize } from '../lib/format'
import { useApi } from '../lib/hooks'
import { appPath } from '../lib/site'
import { useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import {
  Bar,
  Empty,
  Failure,
  Loading,
  Metric,
  Panel,
  Rule,
  SectionHeader,
  StatusMark,
  Tag,
} from '../components/primitives'

export default function Learning() {
  const { status } = useSystem()
  const incidents = useApi<{ incidents: IncidentSummary[] }>(() => api.incidents(50), [], {
    pollMs: 30_000,
  })

  const learning = status?.learning

  // Oldest first: the question is whether effort per incident falls as memory accumulates.
  const chronological = useMemo(
    () => [...(incidents.data?.incidents ?? [])].reverse(),
    [incidents.data],
  )
  const maxAttempts = Math.max(1, ...chronological.map((incident) => incident.attempts ?? 0))

  const rollbacks = chronological.filter((incident) => incident.outcome === 'rolled-back')

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Learning"
          description="The question this page answers: is the agent actually getting better, or merely busier? Every figure is derived from stored incidents."
        />
      </header>

      {/* ── headline rates ───────────────────────────────────── */}
      <section>
        <SectionHeader index="02." title="Measured behaviour" />
        <Panel className="mt-5">
          {!learning ? (
            <Loading label="Reading learning statistics" rows={3} />
          ) : (
            <div className="grid grid-cols-2 gap-px bg-hair lg:grid-cols-4">
              <Metric
                value={percent(learning.repair_success_rate, { from: 'percent' })}
                label="Repair success rate"
                tone="ok"
                note={`${learning.resolved} of ${learning.total_incidents} incidents recovered`}
              />
              <Metric
                value={learning.avg_attempts.toFixed(2)}
                label="Average attempts"
                note="Fewer attempts per incident is the signal that recall is paying off"
              />
              <Metric
                value={percent(learning.first_attempt_success_rate, { from: 'percent' })}
                label="Fixed first attempt"
                note="Repaired without a second proposal"
              />
              <Metric
                value={percent(learning.regression_rate, { from: 'percent' })}
                label="Regression rate"
                tone={learning.regression_rate > 0 ? 'warn' : 'ink'}
                note="Repairs that introduced a new failure"
              />
              <Metric value={learning.memories_recalled} label="Memories recalled" />
              <Metric
                value={learning.historical_fixes_reused}
                label="Fixes reused"
                tone={learning.historical_fixes_reused > 0 ? 'ok' : 'ink'}
                note="Repairs adapted from a recalled incident"
              />
              <Metric
                value={learning.failed_approaches_avoided}
                label="Failed approaches avoided"
                note="Known-bad repairs the agent did not repeat"
              />
              <Metric
                value={learning.rolled_back}
                label="Rollbacks"
                tone={learning.rolled_back > 0 ? 'bad' : 'idle'}
                note={`${learning.escalated} escalated instead of guessing`}
              />
            </div>
          )}
        </Panel>
      </section>

      {/* ── attempts over time ───────────────────────────────── */}
      <section>
        <SectionHeader
          index="03."
          title="Attempts per incident"
          description="Oldest to newest, left to right. A downward trend means earlier incidents are doing work for later ones."
        />
        <Panel className="mt-5">
          {incidents.initial ? (
            <Loading label="Reading incident history" rows={3} />
          ) : incidents.error ? (
            <Failure
              title="Could not read the incident history"
              message={incidents.error.message}
              detail={incidents.error.detail}
              onRetry={incidents.reload}
            />
          ) : chronological.length === 0 ? (
            <Empty
              icon={TrendingUp}
              title="No incidents to compare yet"
              detail="Run at least two incidents of the same class and a trend becomes visible here."
            />
          ) : (
            <div className="p-5">
              <ol className="flex items-end gap-3 overflow-x-auto pb-2" aria-label="Attempts per incident">
                {chronological.map((incident) => {
                  const attempts = incident.attempts ?? 0
                  const height = Math.max(6, Math.round((attempts / maxAttempts) * 96))
                  const recovered = incident.outcome === 'recovered'
                  return (
                    <li key={incident.id} className="flex w-16 shrink-0 flex-col items-center gap-2">
                      <span className="font-mono text-micro tabular text-status-idle">{attempts}</span>
                      <Link
                        to={appPath(`/incidents/${incident.id}`)}
                        title={`${incident.id} — ${titleize(incident.error_class)} — ${incident.outcome ?? 'incomplete'}`}
                        className={`w-full border-2 border-ink transition-colors duration-150 ease-linear hover:border-accent ${
                          recovered ? 'bg-ink hover:bg-accent' : 'bg-accent hover:bg-ink'
                        }`}
                        style={{ height }}
                        aria-label={`${incident.id}: ${attempts} attempts, ${incident.outcome ?? 'incomplete'}`}
                      />
                      <span className="font-mono text-[10px] text-status-idle">
                        {relativeTime(incident.created_at).replace(' ago', '')}
                      </span>
                    </li>
                  )
                })}
              </ol>
              <p className="mt-3 text-micro text-status-idle">
                Black columns recovered; red columns ended in rollback or escalation. Per-incident
                recall counts are on each incident's own page.
              </p>
            </div>
          )}
        </Panel>
      </section>

      {/* ── memory effect ────────────────────────────────────── */}
      <section>
        <SectionHeader index="04." title="Memory pressure" />
        <Panel className="mt-5">
          <div className="grid gap-px bg-hair lg:grid-cols-3">
            <div className="bg-paper p-6">
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Recall vs reuse
              </div>
              <div className="mt-3">
                <Bar
                  value={learning?.historical_fixes_reused ?? 0}
                  max={Math.max(1, learning?.memories_recalled ?? 1)}
                  tone="ok"
                  label="Fixes reused against memories recalled"
                />
              </div>
              <p className="mt-3 text-micro text-status-idle">
                {learning
                  ? `${learning.historical_fixes_reused} of ${learning.memories_recalled} recalled memories were strong enough to base a repair on. The rest were reviewed and set aside.`
                  : 'Awaiting data.'}
              </p>
            </div>
            <div className="bg-paper p-6">
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Retained vs recalled
              </div>
              <div className="mt-3">
                <Bar
                  value={status?.memory.recalls ?? 0}
                  max={Math.max(1, status?.memory.retains ?? 1)}
                  label="Recalls against retains"
                />
              </div>
              <p className="mt-3 text-micro text-status-idle">
                {status
                  ? `${status.memory.retains} writes and ${status.memory.recalls} reads. Reads outpacing writes is the healthy direction.`
                  : 'Awaiting data.'}
              </p>
            </div>
            <div className="bg-paper p-6">
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Failure modes
              </div>
              <ul className="mt-3 space-y-2">
                {(rollbacks.length > 0 ? rollbacks.slice(-4) : []).map((incident) => (
                  <li key={incident.id} className="flex items-center justify-between gap-3">
                    <Link
                      to={appPath(`/incidents/${incident.id}`)}
                      className="font-mono text-micro underline-offset-4 hover:text-accent hover:underline"
                    >
                      {incident.id}
                    </Link>
                    <Tag tone="bad">{incident.error_class ?? 'unknown'}</Tag>
                  </li>
                ))}
                {rollbacks.length === 0 ? (
                  <li className="text-micro text-status-idle">
                    No incident has exhausted its repair budget and rolled back.
                  </li>
                ) : null}
              </ul>
            </div>
          </div>
        </Panel>
      </section>

      {/* ── stored per-incident statistics ───────────────────── */}
      {learning && learning.per_incident.length > 0 ? (
        <section>
          <SectionHeader
            index="05."
            title="Stored statistics"
            description="The aggregates the API reports, shown verbatim so the numbers above can be checked."
          />
          <Panel className="mt-5">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b-2 border-ink">
                    {['Incidents', 'Attempts', 'Recalled', 'Reused', 'First-attempt', 'Rollbacks'].map(
                      (heading) => (
                        <th
                          key={heading}
                          scope="col"
                          className="px-4 py-2.5 text-label font-black uppercase tracking-widest text-status-idle"
                        >
                          {heading}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {learning.per_incident.map((row, index) => (
                    <tr key={index} className="border-b border-hair">
                      <td className="px-4 py-2.5 font-mono text-meta tabular">{row.incidents}</td>
                      <td className="px-4 py-2.5 font-mono text-meta tabular">{row.attempts}</td>
                      <td className="px-4 py-2.5 font-mono text-meta tabular">{row.memories_recalled}</td>
                      <td className="px-4 py-2.5 font-mono text-meta tabular">{row.memories_reused}</td>
                      <td className="px-4 py-2.5 font-mono text-meta tabular">{row.first_attempt_success}</td>
                      <td className="px-4 py-2.5 font-mono text-meta tabular">{row.rollbacks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </section>
      ) : null}

      {/* ── memory health ────────────────────────────────────── */}
      <section>
        <SectionHeader index="06." title="Memory operations" />
        <Panel className="mt-5">
          <div className="flex flex-wrap items-center gap-8 px-6 py-5">
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Retains
              </div>
              <div className="mt-1 text-h3 font-black tabular">{status?.memory.retains ?? 0}</div>
            </div>
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Recalls
              </div>
              <div className="mt-1 text-h3 font-black tabular">{status?.memory.recalls ?? 0}</div>
            </div>
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Reflections
              </div>
              <div className="mt-1 text-h3 font-black tabular">{status?.memory.reflects ?? 0}</div>
            </div>
            <div>
              <div className="text-label font-black uppercase tracking-widest text-status-idle">
                Failed
              </div>
              <div className="mt-1 text-h3 font-black tabular">{status?.memory.failures ?? 0}</div>
            </div>
          </div>
          <Rule />
          <div className="px-6 py-4">
            <StatusMark
              variant={status?.hindsight_ready ? 'ok' : 'warn'}
              label={status?.hindsight_ready ? 'Memory connected' : 'Memory unavailable'}
            />
            <p className="mt-2 text-micro text-status-idle">
              {status?.hindsight_ready
                ? 'Recalled memories are used as evidence, never as truth: a repair is only credited once the sandbox reproduces the failure and the full suite stays clean.'
                : 'While memory is unavailable the agent still investigates, repairs and verifies — it simply cannot learn. Nothing is fabricated to hide that.'}
            </p>
          </div>
        </Panel>
      </section>

      {learning && learning.per_incident.length === 0 && learning.total_incidents > 0 ? (
        <p className="text-micro text-status-idle">
          The API reports {learning.total_incidents} incident(s) but no per-incident breakdown is
          available yet.
        </p>
      ) : null}
    </Page>
  )
}
