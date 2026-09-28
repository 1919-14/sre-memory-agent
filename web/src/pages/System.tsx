import { Activity, RefreshCw } from 'lucide-react'

import { localDateTime } from '../lib/format'
import { useRefreshAfter, useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import { ActivityStream } from '../components/ActivityStream'
import {
  Btn,
  Failure,
  KV,
  Loading,
  Panel,
  SectionHeader,
  StatusMark,
  Tag,
} from '../components/primitives'

export default function System() {
  const { status, statusError, statusLoading, reloadStatus, stream } = useSystem()
  const refresh = useRefreshAfter()

  if (statusLoading) {
    return (
      <Page>
        <Loading label="Reading system status" rows={6} />
      </Page>
    )
  }

  if (statusError || !status) {
    return (
      <Page className="space-y-8">
        <SectionHeader index="01." title="System" description="Health and configuration of every dependency." />
        <Failure
          title="Status unavailable"
          message={statusError?.message ?? 'The backend did not return a status payload.'}
          detail={statusError?.detail}
          onRetry={reloadStatus}
        />
      </Page>
    )
  }

  const dependencies = [
    {
      label: 'Agent',
      ok: status.healthy,
      value: status.healthy ? 'Operational' : 'Degraded',
      detail: status.running ? 'An incident is running' : 'Idle',
    },
    {
      label: 'Hindsight memory',
      ok: status.hindsight_ready,
      value: status.hindsight_ready ? 'Connected' : 'Unavailable',
      detail: status.hindsight_detail,
    },
    {
      label: 'LLM provider',
      ok: status.llm_ready,
      value: status.llm_ready ? 'Connected' : 'Not configured',
      detail: status.llm_ready
        ? 'Classification, patch generation and review'
        : 'Set GROQ_API_KEY in .env to enable reasoning',
    },
    {
      label: 'Docker',
      ok: status.docker_available,
      value: status.docker_available ? 'Available' : 'Not running',
      detail: status.docker_available
        ? 'Container isolation is available for the sandbox'
        : 'The sandbox falls back to a temporary workspace on the host',
    },
    {
      label: 'Sandbox backend',
      ok: status.sandbox_backend === 'docker',
      value: status.sandbox_backend,
      detail:
        status.sandbox_backend === 'docker'
          ? 'Generated code runs in a container with no network access'
          : 'Generated code runs in a temp workspace, bounded by the validator and review gate',
    },
    {
      label: 'Target repository',
      ok: status.repo_present,
      value: status.repo_present ? 'Found' : 'Missing',
      detail: status.repo_path,
    },
  ]

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="System"
          description="Health and configuration of every dependency the agent needs, and the states it degrades into when one is missing."
          action={
            <Btn icon={RefreshCw} size="sm" variant="secondary" onClick={refresh}>
              Re-check
            </Btn>
          }
        />
      </header>

      {status.warnings.length > 0 ? (
        <Failure
          warning
          title={`${status.warnings.length} active warning${status.warnings.length === 1 ? '' : 's'}`}
          message={status.warnings[0]}
          detail={status.warnings.join('\n\n')}
          onRetry={refresh}
          retryLabel="Re-check"
        />
      ) : (
        <Panel className="border-status-ok">
          <div className="p-5">
            <StatusMark variant="ok" label="No warnings" />
            <p className="mt-2 text-meta text-status-idle">
              Every dependency reported healthy on the last check.
            </p>
          </div>
          {status.notes.length > 0 ? (
            <ul className="divide-y divide-hair border-t-2 border-hair">
              {status.notes.map((note) => (
                <li key={note} className="px-5 py-3 font-mono text-micro text-status-idle">
                  {note}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      )}

      {/* ── dependencies ─────────────────────────────────────── */}
      <section>
        <SectionHeader index="02." title="Dependencies" />
        <Panel className="mt-5">
          <div className="grid grid-cols-1 gap-px bg-hair lg:grid-cols-2">
            {dependencies.map((dependency) => (
              <div key={dependency.label} className="bg-paper px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-label font-black uppercase tracking-widest text-status-idle">
                    {dependency.label}
                  </span>
                  <StatusMark
                    variant={dependency.ok ? 'ok' : 'warn'}
                    label={dependency.value}
                  />
                </div>
                <p className="mt-2 break-words text-micro text-status-idle" title={dependency.detail}>
                  {dependency.detail}
                </p>
              </div>
            ))}
          </div>
        </Panel>
      </section>

      {/* ── identity ─────────────────────────────────────────── */}
      <section>
        <SectionHeader index="03." title="Runtime" />
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <Panel className="p-5">
            <div className="text-label font-black uppercase tracking-widest text-accent">
              Service
            </div>
            <dl className="mt-3">
              <KV k="Version" mono>
                {status.version}
              </KV>
              <KV k="Environment" mono>
                {status.run_mode}
              </KV>
              <KV k="Hindsight version" mono>
                {status.hindsight_version || '—'}
              </KV>
              <KV k="Active incident" mono>
                {status.active_incident_id ?? 'none'}
              </KV>
              <KV k="Stream" mono>
                {stream.state}
              </KV>
            </dl>
          </Panel>

          <Panel className="p-5">
            <div className="text-label font-black uppercase tracking-widest text-accent">
              Repository and banks
            </div>
            <dl className="mt-3">
              <KV k="Repository" mono>
                <span className="break-all">{status.repo_path}</span>
              </KV>
              <KV k="Commit" mono>
                {status.repo_commit || '—'}
              </KV>
              <KV k="Incident bank" mono>
                {status.banks.incident}
              </KV>
              <KV k="Convention bank" mono>
                {status.banks.conventions}
              </KV>
              <KV k="Memory defense" align="stack">
                {status.memory_defense || 'not reported'}
              </KV>
            </dl>
          </Panel>
        </div>
      </section>

      {/* ── credentials ──────────────────────────────────────── */}
      <section>
        <SectionHeader index="04." title="Credentials" />
        <Panel className="mt-5">
          {status.missing_credentials.length === 0 ? (
            <div className="p-5">
              <StatusMark variant="ok" label="Nothing missing" />
              <p className="mt-2 text-meta text-status-idle">
                Every credential the current run mode needs is configured.
              </p>
            </div>
          ) : (
            <div className="p-5">
              <StatusMark variant="bad" label="Missing credentials" />
              <ul className="mt-3 space-y-1">
                {status.missing_credentials.map((name) => (
                  <li key={name} className="font-mono text-meta text-status-bad">
                    {name}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-meta text-status-idle">
                Add these to <span className="font-mono">.env</span> and restart the backend. They
                are never displayed here, only their absence.
              </p>
            </div>
          )}
        </Panel>
      </section>

      {/* ── activity ─────────────────────────────────────────── */}
      <section>
        <SectionHeader
          index="05."
          title="Live event stream"
          description="The raw feed the agent publishes. The same stream powers the activity panel on the overview."
          action={<Tag tone={stream.state === 'live' ? 'ok' : 'neutral'}>{stream.state}</Tag>}
        />
        <Panel className="mt-5">
          <ActivityStream events={stream.events.slice(-120)} height="30rem" />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t-2 border-hair px-5 py-3">
            <span className="font-mono text-micro text-status-idle">
              {stream.events.length} event(s) buffered · last at{' '}
              {stream.events.length
                ? localDateTime(stream.events[stream.events.length - 1].timestamp)
                : '—'}
            </span>
            <Btn icon={Activity} size="sm" variant="ghost" onClick={stream.clear}>
              Clear buffer
            </Btn>
          </div>
        </Panel>
      </section>
    </Page>
  )
}
