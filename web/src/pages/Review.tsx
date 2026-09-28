import { ShieldCheck } from 'lucide-react'

import { localDateTime, plural, severityRank, titleize } from '../lib/format'
import { useSelectedIncident } from '../lib/hooks'
import { Page } from '../components/AppShell'
import { IncidentPicker } from '../components/IncidentTable'
import { MemoryCard } from '../components/MemoryCard'
import {
  Empty,
  Failure,
  KV,
  Loading,
  Panel,
  SectionHeader,
  SeverityTag,
  StatusMark,
  Tag,
} from '../components/primitives'

export default function Review() {
  const { incidents, selectedId, select, incident, listLoading, listError, reloadList } =
    useSelectedIncident()

  const data = incident.data
  const reviewed = (data?.attempts ?? []).filter((attempt) => attempt.review)

  const counts = reviewed.reduce(
    (accumulator, attempt) => {
      const decision = attempt.review?.decision ?? 'unknown'
      accumulator[decision] = (accumulator[decision] ?? 0) + 1
      return accumulator
    },
    {} as Record<string, number>,
  )

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Review gate"
          description="Every generated patch is reviewed before it is allowed to execute. Deterministic policy checks run first; the convention reviewer checks the change against rules the agent remembers."
          action={
            incidents.length > 0 ? (
              <IncidentPicker incidents={incidents} value={selectedId} onChange={select} />
            ) : undefined
          }
        />
      </header>

      {listError ? (
        <Failure
          title="Could not read the incident list"
          message={listError.message}
          detail={listError.detail}
          onRetry={reloadList}
        />
      ) : listLoading ? (
        <Panel>
          <Loading label="Loading incidents" rows={4} />
        </Panel>
      ) : incidents.length === 0 ? (
        <Panel>
          <Empty
            icon={ShieldCheck}
            title="No reviews recorded"
            detail="No incident has run yet, so no patch has reached the review gate."
          />
        </Panel>
      ) : incident.initial ? (
        <Panel>
          <Loading label="Loading review decisions" rows={5} />
        </Panel>
      ) : incident.error ? (
        <Failure
          title="Could not load the review record"
          message={incident.error.message}
          detail={incident.error.detail}
          onRetry={incident.reload}
        />
      ) : reviewed.length === 0 ? (
        <Panel>
          <div className="p-6">
            <div className="text-meta font-black uppercase tracking-wide text-ink">
              No patch reached the review gate
            </div>
            <p className="mt-2 max-w-2xl text-meta text-status-idle">
              {data?.outcome === 'escalated'
                ? 'This incident was escalated before any patch was proposed, which is the correct outcome when the failure is not code-fixable.'
                : 'The run produced no candidate patch for the gate to evaluate.'}
            </p>
          </div>
        </Panel>
      ) : (
        <>
          <Panel>
            <div className="flex flex-wrap items-center gap-6 px-6 py-5">
              <div>
                <div className="text-label font-black uppercase tracking-widest text-status-idle">
                  Patches reviewed
                </div>
                <div className="mt-1 text-h2 font-black tabular">{reviewed.length}</div>
              </div>
              {Object.entries(counts).map(([decision, count]) => (
                <div key={decision}>
                  <div className="text-label font-black uppercase tracking-widest text-status-idle">
                    {decision}
                  </div>
                  <div className="mt-1 text-h2 font-black tabular">{count}</div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="space-y-8">
            {reviewed.map((attempt) => {
              const verdict = attempt.review!
              const ordered = [...verdict.findings].sort(
                (a, b) => severityRank(b.severity) - severityRank(a.severity),
              )
              const deterministic = ordered.filter((finding) => finding.reviewer === 'policy')
              const memoryInformed = ordered.filter((finding) => finding.reviewer !== 'policy')

              return (
                <Panel key={attempt.number}>
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-ink px-5 py-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="font-mono text-meta font-bold">
                        Attempt {String(attempt.number).padStart(2, '0')}
                      </span>
                      <StatusMark
                        variant={
                          verdict.decision === 'approve'
                            ? 'ok'
                            : verdict.decision === 'reject'
                              ? 'bad'
                              : 'warn'
                        }
                        label={verdict.decision.toUpperCase()}
                      />
                      {verdict.reviewers_run.map((reviewer) => (
                        <Tag key={reviewer} tone="neutral">
                          {reviewer}
                        </Tag>
                      ))}
                      <Tag tone="neutral">{plural(verdict.cycles, 'cycle')}</Tag>
                    </div>
                    <span className="font-mono text-micro text-status-idle">
                      {localDateTime(verdict.evaluated_at)}
                    </span>
                  </div>

                  <div className="p-5">
                    <p className="max-w-3xl text-lead">{verdict.summary}</p>

                    <div className="mt-6 grid gap-8 lg:grid-cols-2">
                      <div>
                        <div className="text-label font-black uppercase tracking-widest text-ink">
                          Deterministic checks
                        </div>
                        {deterministic.length === 0 ? (
                          <p className="mt-3 text-meta text-status-idle">
                            No policy findings. Patch scope, secrets, destructive operations and
                            test-integrity checks all passed.
                          </p>
                        ) : (
                          <ul className="mt-3 space-y-3">
                            {deterministic.map((finding, index) => (
                              <li key={index} className="flex items-start gap-3">
                                <SeverityTag severity={finding.severity} />
                                <div className="min-w-0">
                                  <div className="text-meta font-bold">{finding.rule}</div>
                                  <p className="mt-0.5 text-micro text-status-idle">
                                    {finding.message}
                                  </p>
                                  {finding.file ? (
                                    <p className="mt-1 font-mono text-micro text-status-idle">
                                      {finding.file}
                                      {finding.line ? `:${finding.line}` : ''}
                                    </p>
                                  ) : null}
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>

                      <div>
                        <div className="text-label font-black uppercase tracking-widest text-ink">
                          Memory-informed review
                        </div>
                        {memoryInformed.length === 0 ? (
                          <p className="mt-3 text-meta text-status-idle">
                            {data?.convention_refs.length
                              ? 'The change was checked against remembered conventions and no conflicts were found.'
                              : 'No convention memory was available for this repository, so only deterministic checks applied.'}
                          </p>
                        ) : (
                          <ul className="mt-3 space-y-3">
                            {memoryInformed.map((finding, index) => (
                              <li key={index} className="flex items-start gap-3">
                                <SeverityTag severity={finding.severity} />
                                <div className="min-w-0">
                                  <div className="text-meta font-bold">{finding.rule}</div>
                                  <p className="mt-0.5 text-micro text-status-idle">
                                    {finding.message}
                                  </p>
                                  {finding.memory_text ? (
                                    <p className="mt-2 border-l-2 border-accent pl-3 text-micro text-status-idle">
                                      Remembered rule: {finding.memory_text}
                                    </p>
                                  ) : null}
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>

                    <dl className="mt-8 max-w-2xl">
                      {attempt.patch?.summary ? (
                        <KV k="Patch under review" align="stack">
                          {attempt.patch.summary}
                        </KV>
                      ) : null}
                      {attempt.strategy ? (
                        <KV k="Strategy" mono>
                          {titleize(attempt.strategy)}
                        </KV>
                      ) : null}
                      <KV k="Conventions consulted" mono>
                        {data?.convention_refs.length ?? 0}
                      </KV>
                    </dl>
                  </div>

                  {data && data.convention_refs.length > 0 ? (
                    <div className="border-t-2 border-hair p-5">
                      <div className="text-label font-black uppercase tracking-widest text-status-idle">
                        Rules this review was measured against
                      </div>
                      <div className="mt-3 space-y-4">
                        {data.convention_refs.map((memory) => (
                          <MemoryCard key={memory.memory_id} memory={memory} compact />
                        ))}
                      </div>
                    </div>
                  ) : null}
                </Panel>
              )
            })}
          </div>
        </>
      )}
    </Page>
  )
}
