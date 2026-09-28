import { Box } from 'lucide-react'

import { duration, plural } from '../lib/format'
import { useSelectedIncident } from '../lib/hooks'
import { Page } from '../components/AppShell'
import { IncidentPicker } from '../components/IncidentTable'
import { BeforeAfter, TestPanel } from '../components/TestPanel'
import {
  Empty,
  Failure,
  KV,
  Loading,
  Panel,
  SectionHeader,
  StatusMark,
  Tag,
  type Variant,
} from '../components/primitives'

export default function Sandbox() {
  const { incidents, selectedId, select, incident, listLoading, listError, reloadList } =
    useSelectedIncident()

  const data = incident.data
  const runs = (data?.attempts ?? []).filter((attempt) => attempt.sandbox)

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Sandbox"
          description="Where generated code is allowed to run. The failure is reproduced unpatched first, so a fix cannot be credited for a test run that executed nothing."
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
            icon={Box}
            title="Nothing has been executed"
            detail="No incident has run yet, so the sandbox has not been used."
          />
        </Panel>
      ) : incident.initial ? (
        <Panel>
          <Loading label="Loading sandbox results" rows={6} />
        </Panel>
      ) : incident.error ? (
        <Failure
          title="Could not load sandbox results"
          message={incident.error.message}
          detail={incident.error.detail}
          onRetry={incident.reload}
        />
      ) : runs.length === 0 ? (
        <Panel>
          <div className="p-6">
            <div className="text-meta font-black uppercase tracking-wide text-ink">
              No patch was executed
            </div>
            <p className="mt-2 max-w-2xl text-meta text-status-idle">
              {data?.outcome === 'escalated'
                ? 'This incident was escalated, so the sandbox was deliberately never used. Nothing unverified was allowed to run.'
                : 'No candidate patch survived to the execution stage for this incident.'}
            </p>
          </div>
        </Panel>
      ) : (
        <div className="space-y-8">
          {runs.map((attempt) => {
            const sandbox = attempt.sandbox!
            const verified = sandbox.error_reproduced && (sandbox.test_report?.failed ?? 1) === 0

            return (
              <Panel key={attempt.number}>
                <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-ink px-5 py-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-mono text-meta font-bold">
                      Attempt {String(attempt.number).padStart(2, '0')}
                    </span>
                    <StatusMark
                      variant={(verified ? 'ok' : 'bad') as Variant}
                      label={verified ? 'verified' : 'not verified'}
                    />
                    <Tag tone={sandbox.backend === 'docker' ? 'ok' : 'neutral'}>{sandbox.backend}</Tag>
                    {sandbox.isolated ? <Tag tone="ok">isolated</Tag> : <Tag tone="warn">not isolated</Tag>}
                    {sandbox.simulated ? <Tag tone="warn">simulated</Tag> : null}
                  </div>
                  <span className="font-mono text-micro text-status-idle">
                    {duration(sandbox.duration_s)}
                  </span>
                </div>

                {sandbox.simulated ? (
                  <p className="border-b-2 border-hair bg-muted px-5 py-3 text-micro text-status-warn">
                    The backend marks this execution as simulated. Its results are not a live
                    sandbox run and should not be read as one.
                  </p>
                ) : null}

                <div className="p-5">
                  <BeforeAfter
                    before={sandbox.reproduce_report}
                    after={sandbox.full_report}
                  />

                  <div className="mt-6 grid gap-5 lg:grid-cols-2">
                    <div>
                      <div className="text-label font-black uppercase tracking-widest text-ink">
                        Execution steps
                      </div>
                      <dl className="mt-2">
                        <KV k="Reproduce original failure">
                          <StatusMark
                            variant={sandbox.error_reproduced ? 'ok' : 'bad'}
                            label={
                              sandbox.error_reproduced
                                ? `${plural(sandbox.reproduce_report?.failed ?? 0, 'test')} failed as expected`
                                : 'not reproduced'
                            }
                          />
                        </KV>
                        <KV k="Apply patch">
                          <StatusMark
                            variant={sandbox.patch_applied ? 'ok' : 'bad'}
                            label={sandbox.patch_applied ? 'applied' : 'not applied'}
                          />
                        </KV>
                        <KV k="Run targeted tests">
                          <StatusMark
                            variant={(sandbox.test_report?.failed ?? 1) === 0 ? 'ok' : 'bad'}
                            label={
                              sandbox.test_report
                                ? `${sandbox.test_report.passed} passed / ${sandbox.test_report.failed} failed`
                                : 'not run'
                            }
                          />
                        </KV>
                        <KV k="Run full suite">
                          <StatusMark
                            variant={(sandbox.full_report?.failed ?? 1) === 0 ? 'ok' : 'bad'}
                            label={
                              sandbox.full_report
                                ? `${sandbox.full_report.passed} passed / ${sandbox.full_report.failed} failed`
                                : 'not run'
                            }
                          />
                        </KV>
                        {attempt.regression ? (
                          <KV k="Regression check">
                            <StatusMark
                              variant={attempt.regression.acceptable ? 'ok' : 'bad'}
                              label={
                                attempt.regression.acceptable
                                  ? 'no new failures'
                                  : `${plural(attempt.regression.new_failures.length, 'new failure')}`
                              }
                            />
                          </KV>
                        ) : null}
                      </dl>
                    </div>

                    <div>
                      <div className="text-label font-black uppercase tracking-widest text-ink">
                        Environment
                      </div>
                      <dl className="mt-2">
                        <KV k="Started" mono>
                          {sandbox.started ? 'yes' : 'no'}
                        </KV>
                        <KV k="Backend" mono>
                          {sandbox.backend}
                        </KV>
                        <KV k="Workspace" mono>
                          <span className="break-all">{sandbox.workspace || '—'}</span>
                        </KV>
                      </dl>
                      {!sandbox.isolated ? (
                        <p className="mt-3 border-l-2 border-status-warn pl-3 text-micro text-status-warn">
                          This backend does not provide container isolation. Generated code ran in a
                          temporary workspace on the host, bounded by the patch validator and the
                          review gate rather than by a container.
                        </p>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-6 space-y-5">
                    <TestPanel
                      title="Failure reproduction (before the patch)"
                      report={sandbox.reproduce_report}
                    />
                    <TestPanel title="Targeted verification (after the patch)" report={sandbox.test_report} />
                    <TestPanel title="Full suite (after the patch)" report={sandbox.full_report} />
                  </div>

                  {sandbox.output ? (
                    <details className="mt-5">
                      <summary className="cursor-pointer text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent">
                        Runner output
                      </summary>
                      <pre className="code-surface mt-3 max-h-72 overflow-auto p-4 text-micro">
                        {sandbox.output}
                      </pre>
                    </details>
                  ) : null}

                  {sandbox.error ? (
                    <p className="mt-5 border-l-4 border-status-bad pl-4 text-meta text-status-bad">
                      {sandbox.error}
                    </p>
                  ) : null}
                </div>
              </Panel>
            )
          })}
        </div>
      )}
    </Page>
  )
}
