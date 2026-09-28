import { DatabaseZap, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { api } from '../lib/api'
import { useRefreshAfter, useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import { Btn, Failure, KV, Loading, Panel, SectionHeader, Tag } from '../components/primitives'

/**
 * Configuration is environment-driven, so there is nothing to edit here. Showing the
 * values the backend is actually running with is more useful than a form that silently
 * disagrees with `.env`.
 */
export default function Settings() {
  const { status, statusLoading, statusError, reloadStatus } = useSystem()
  const refresh = useRefreshAfter()
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const act = async (key: string, run: () => Promise<string>) => {
    setBusy(key)
    setFailure(null)
    setNote(null)
    try {
      const message = await run()
      setNote(message)
      refresh()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'The action failed.')
    } finally {
      setBusy(null)
    }
  }

  if (statusLoading) {
    return (
      <Page>
        <Loading label="Reading configuration" rows={6} />
      </Page>
    )
  }

  if (statusError || !status) {
    return (
      <Page className="space-y-8">
        <SectionHeader index="01." title="Settings" description="The configuration the backend is running with." />
        <Failure
          title="Configuration unavailable"
          message={statusError?.message ?? 'The backend did not return a status payload.'}
          detail={statusError?.detail}
          onRetry={reloadStatus}
        />
      </Page>
    )
  }

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Settings"
          description="Everything here is read from the running backend, which takes its configuration from the environment. Editing .env and restarting is the way to change it — this page will not pretend otherwise."
        />
      </header>

      <Panel className="border-ink p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Tag tone="neutral">.env</Tag>
          <span className="text-meta text-status-idle">
            Changes to <span className="font-mono">.env</span> require restarting the backend.
          </span>
        </div>
      </Panel>

      <div className="grid gap-8 lg:grid-cols-2">
        <section>
          <SectionHeader index="02." title="Reasoning" />
          <Panel className="mt-5 p-5">
            <dl>
              <KV k="LLM provider" mono>
                {status.llm_ready ? 'configured' : 'not configured'}
              </KV>
              <KV k="Run mode" mono>
                {status.run_mode}
              </KV>
              <KV k="Missing credentials" mono>
                {status.missing_credentials.length ? status.missing_credentials.join(', ') : 'none'}
              </KV>
            </dl>
            <p className="mt-3 text-micro text-status-idle">
              Model names, temperature and retry limits are environment settings and cannot be read
              from the browser without exposing configuration the API deliberately does not publish.
            </p>
          </Panel>
        </section>

        <section>
          <SectionHeader index="03." title="Memory" />
          <Panel className="mt-5 p-5">
            <dl>
              <KV k="Incident bank" mono>
                {status.banks.incident}
              </KV>
              <KV k="Convention bank" mono>
                {status.banks.conventions}
              </KV>
              <KV k="Memory defense" align="stack">
                {status.memory_defense || 'not reported'}
              </KV>
              <KV k="Retains" mono>
                {status.memory.retains}
              </KV>
              <KV k="Recalls" mono>
                {status.memory.recalls}
              </KV>
            </dl>
          </Panel>
        </section>

        <section>
          <SectionHeader index="04." title="Execution" />
          <Panel className="mt-5 p-5">
            <dl>
              <KV k="Sandbox backend" mono>
                {status.sandbox_backend}
              </KV>
              <KV k="Docker" mono>
                {status.docker_available ? 'available' : 'not running'}
              </KV>
              <KV k="Repository" mono>
                <span className="break-all">{status.repo_path}</span>
              </KV>
              <KV k="Commit" mono>
                {status.repo_commit || '—'}
              </KV>
            </dl>
          </Panel>
        </section>

        <section>
          <SectionHeader index="05." title="Operations" />
          <Panel className="mt-5">
            <div className="space-y-5 p-5">
              <div>
                <div className="text-meta font-bold uppercase tracking-wide">Seed convention memory</div>
                <p className="mt-1 text-micro text-status-idle">
                  Writes this repository's standing conventions into the convention bank so the
                  review gate has rules to check against. Safe to repeat.
                </p>
                <div className="mt-3">
                  <Btn
                    icon={DatabaseZap}
                    size="sm"
                    variant="secondary"
                    disabled={busy !== null || !status.hindsight_ready}
                    onClick={() =>
                      void act('seed', async () => {
                        await api.seedMemory()
                        return 'Convention memory seeded.'
                      })
                    }
                  >
                    {busy === 'seed' ? 'Seeding' : 'Seed memory'}
                  </Btn>
                </div>
              </div>

              <div className="border-t-2 border-hair pt-5">
                <div className="text-meta font-bold uppercase tracking-wide">
                  Clear the local operational record
                </div>
                <p className="mt-1 text-micro text-status-idle">
                  Empties the incident and event store used by this dashboard. Hindsight memory is
                  deliberately untouched, so the agent keeps everything it has learned.
                </p>
                <div className="mt-3">
                  <Btn
                    icon={RotateCcw}
                    size="sm"
                    variant="secondary"
                    disabled={busy !== null}
                    onClick={() =>
                      void act('reset', async () => {
                        const result = await api.resetDemo()
                        return result.note || 'Operational record cleared.'
                      })
                    }
                  >
                    {busy === 'reset' ? 'Clearing' : 'Clear record'}
                  </Btn>
                </div>
              </div>

              {note ? (
                <p className="border-l-2 border-status-ok pl-3 text-micro text-status-ok">{note}</p>
              ) : null}
              {failure ? (
                <p className="border-l-2 border-status-bad pl-3 text-micro text-status-bad">{failure}</p>
              ) : null}
            </div>
          </Panel>
        </section>
      </div>
    </Page>
  )
}
