import { Wrench } from 'lucide-react'

import { duration, titleize } from '../lib/format'
import { useSelectedIncident } from '../lib/hooks'
import { Page } from '../components/AppShell'
import { DiffViewer } from '../components/DiffViewer'
import { IncidentPicker } from '../components/IncidentTable'
import { TestPanel } from '../components/TestPanel'
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
  type Variant,
} from '../components/primitives'

function attemptVariant(status: string): Variant {
  const value = status.toLowerCase()
  if (value.includes('recover') || value.includes('success') || value.includes('verified')) return 'ok'
  if (value.includes('reject') || value.includes('fail')) return 'bad'
  if (value.includes('pending') || value.includes('review')) return 'warn'
  return 'idle'
}

export default function Repairs() {
  const { incidents, selectedId, select, incident, listLoading, listError, reloadList } =
    useSelectedIncident()

  const data = incident.data
  const attempts = data?.attempts ?? []

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Repairs"
          description="Every patch the agent produced, what it was based on, and whether it survived the review gate and the sandbox."
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
            icon={Wrench}
            title="No repairs recorded"
            detail="No incident has run yet, so there are no generated patches to show."
          />
        </Panel>
      ) : incident.initial ? (
        <Panel>
          <Loading label="Loading repairs" rows={6} />
        </Panel>
      ) : incident.error ? (
        <Failure
          title="Could not load this incident's repairs"
          message={incident.error.message}
          detail={incident.error.detail}
          onRetry={incident.reload}
        />
      ) : attempts.length === 0 ? (
        <Panel>
          <div className="p-6">
            <div className="text-meta font-black uppercase tracking-wide text-ink">
              No patch was generated
            </div>
            <p className="mt-2 max-w-2xl text-meta text-status-idle">
              {data?.outcome === 'escalated'
                ? `This incident was escalated rather than repaired: ${data.escalation_reason ?? 'no code change could fix it.'}`
                : 'The agent produced no candidate patch for this incident.'}
            </p>
          </div>
        </Panel>
      ) : (
        <div className="space-y-8">
          {attempts.map((attempt) => (
            <Panel key={attempt.number}>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-ink px-5 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-mono text-meta font-bold">
                    Attempt {String(attempt.number).padStart(2, '0')}
                  </span>
                  <StatusMark variant={attemptVariant(attempt.status)} label={attempt.status} />
                  <Tag tone={attempt.patch?.derived_from_incident ? 'accent' : 'neutral'}>
                    {attempt.patch?.source ?? attempt.source}
                  </Tag>
                  {attempt.strategy ? <Tag tone="neutral">{titleize(attempt.strategy)}</Tag> : null}
                </div>
                <span className="font-mono text-micro text-status-idle">
                  {duration(attempt.duration_s)}
                </span>
              </div>

              <div className="grid gap-8 p-5 lg:grid-cols-3">
                <div className="space-y-5 lg:col-span-2">
                  {attempt.error ? (
                    <p className="border-l-4 border-status-bad pl-4 text-meta text-status-bad">
                      {attempt.error}
                    </p>
                  ) : null}

                  {attempt.patch?.proposed_fix ? (
                    <div>
                      <div className="text-label font-black uppercase tracking-widest text-status-idle">
                        Proposed fix
                      </div>
                      <p className="mt-1.5 text-meta">{attempt.patch.proposed_fix}</p>
                    </div>
                  ) : null}

                  {attempt.patch?.diff ? (
                    <DiffViewer diff={attempt.patch.diff} label={`Attempt ${attempt.number} patch`} />
                  ) : null}

                  {attempt.patch?.files && attempt.patch.files.length > 0 ? (
                    <details>
                      <summary className="cursor-pointer text-label font-bold uppercase tracking-widest text-status-idle transition-colors hover:text-accent">
                        Resulting file contents ({attempt.patch.files.length})
                      </summary>
                      <div className="mt-3 space-y-3">
                        {attempt.patch.files.map((file) => (
                          <div key={file.path} className="border-2 border-hair">
                            <div className="border-b-2 border-hair px-3 py-2 font-mono text-micro">
                              {file.path}
                            </div>
                            <pre className="code-surface max-h-72 overflow-auto p-3 text-micro">
                              {file.content}
                            </pre>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>

                <div className="space-y-5">
                  <dl>
                    {attempt.patch?.root_cause ? (
                      <KV k="Root cause" align="stack">
                        {attempt.patch.root_cause}
                      </KV>
                    ) : null}
                    {attempt.patch?.expected_outcome ? (
                      <KV k="Expected outcome" align="stack">
                        {attempt.patch.expected_outcome}
                      </KV>
                    ) : null}
                    {attempt.patch?.risk ? (
                      <KV k="Risk" align="stack">
                        {attempt.patch.risk}
                      </KV>
                    ) : null}
                    {attempt.patch?.test_strategy ? (
                      <KV k="Test strategy" align="stack">
                        {attempt.patch.test_strategy}
                      </KV>
                    ) : null}
                    {attempt.patch?.addresses_root_cause !== undefined ? (
                      <KV k="Addresses root cause">
                        <StatusMark
                          variant={attempt.patch.addresses_root_cause ? 'ok' : 'warn'}
                          label={attempt.patch.addresses_root_cause ? 'yes' : 'doubtful'}
                        />
                      </KV>
                    ) : null}
                  </dl>

                  {attempt.validation ? (
                    <div className="border-2 border-hair p-4">
                      <div className="text-label font-black uppercase tracking-widest text-status-idle">
                        Patch validation
                      </div>
                      <div className="mt-2 flex items-center gap-3">
                        <StatusMark
                          variant={attempt.validation.ok ? 'ok' : 'bad'}
                          label={attempt.validation.ok ? 'passed' : 'blocked'}
                        />
                        <span className="font-mono text-micro text-status-idle">
                          {attempt.validation.files_changed} file(s) · +
                          {attempt.validation.lines_added}/−{attempt.validation.lines_removed}
                        </span>
                      </div>
                      {attempt.validation.errors.length > 0 ? (
                        <ul className="mt-3 space-y-1">
                          {attempt.validation.errors.map((error) => (
                            <li key={error} className="text-micro text-status-bad">
                              {error}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {attempt.validation.warnings.length > 0 ? (
                        <ul className="mt-3 space-y-1">
                          {attempt.validation.warnings.map((warning) => (
                            <li key={warning} className="text-micro text-status-warn">
                              {warning}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  {attempt.review ? (
                    <div className="border-2 border-hair p-4">
                      <div className="text-label font-black uppercase tracking-widest text-status-idle">
                        Review
                      </div>
                      <div className="mt-2">
                        <StatusMark
                          variant={
                            attempt.review.decision === 'approve'
                              ? 'ok'
                              : attempt.review.decision === 'reject'
                                ? 'bad'
                                : 'warn'
                          }
                          label={attempt.review.decision}
                        />
                      </div>
                      <p className="mt-2 text-micro text-status-idle">{attempt.review.summary}</p>
                      {attempt.review.findings.length > 0 ? (
                        <ul className="mt-3 space-y-2">
                          {attempt.review.findings.map((finding, index) => (
                            <li key={`${finding.rule}-${index}`} className="flex items-start gap-2">
                              <SeverityTag severity={finding.severity} />
                              <span className="text-micro text-status-idle">{finding.rule}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  {attempt.regression ? (
                    <div className="border-2 border-hair p-4">
                      <div className="text-label font-black uppercase tracking-widest text-status-idle">
                        Regression
                      </div>
                      <div className="mt-2">
                        <StatusMark
                          variant={attempt.regression.acceptable ? 'ok' : 'bad'}
                          label={attempt.regression.acceptable ? 'clean' : 'regression'}
                        />
                      </div>
                      <p className="mt-2 text-micro text-status-idle">
                        {attempt.regression.new_failures.length} new failure(s),{' '}
                        {attempt.regression.resolved_failures.length} resolved
                      </p>
                    </div>
                  ) : null}
                </div>
              </div>

              {attempt.sandbox ? (
                <div className="border-t-2 border-hair p-5">
                  <div className="mb-3 text-label font-black uppercase tracking-widest text-status-idle">
                    Sandbox verification
                  </div>
                  <TestPanel title="Targeted tests after the patch" report={attempt.sandbox.test_report} />
                </div>
              ) : null}
            </Panel>
          ))}
        </div>
      )}
    </Page>
  )
}
