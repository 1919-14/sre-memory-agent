import { BrainCircuit, Database, RefreshCw, Search } from 'lucide-react'
import { useState } from 'react'

import { api, type MemoryRef } from '../lib/api'
import { localDateTime } from '../lib/format'
import { useApi } from '../lib/hooks'
import { useSystem } from '../lib/system'
import { Page } from '../components/AppShell'
import { MemoryCard } from '../components/MemoryCard'
import {
  Btn,
  Empty,
  Failure,
  Loading,
  Metric,
  Panel,
  Rule,
  SectionHeader,
  Tag,
} from '../components/primitives'

export default function Memory() {
  const { status } = useSystem()
  const memory = useApi(() => api.memory(), [], { pollMs: 30_000 })
  const runbook = useApi(() => api.runbook(), [], { pollMs: 60_000 })
  const conventions = useApi(() => api.conventions(), [], { pollMs: 60_000 })

  const [query, setQuery] = useState('')
  const [bank, setBank] = useState<'incident' | 'conventions'>('incident')
  const [results, setResults] = useState<MemoryRef[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchNote, setSearchNote] = useState<string | null>(null)

  const runSearch = async () => {
    if (query.trim().length < 2) {
      setSearchNote('Enter at least two characters.')
      return
    }
    setSearching(true)
    setSearchNote(null)
    try {
      const response = await api.memorySearch(query.trim(), bank)
      setResults(response.results ?? [])
      if (response.available === false) {
        setSearchNote(response.detail ?? 'Memory search is unavailable.')
      } else if ((response.results ?? []).length === 0) {
        setSearchNote('No memories matched that query.')
      }
    } catch (error) {
      setSearchNote(error instanceof Error ? error.message : 'Search failed.')
      setResults(null)
    } finally {
      setSearching(false)
    }
  }

  const available = memory.data?.available ?? false
  const incidentMemories = memory.data?.banks?.incident?.memories ?? []
  const conventionMemories = memory.data?.banks?.conventions?.memories ?? []
  const incidentBankError = (memory.data?.banks?.incident as { error?: string } | undefined)?.error

  return (
    <Page className="space-y-12">
      <header>
        <SectionHeader
          index="01."
          title="Memory"
          description="What the agent has written to Hindsight, what it can recall, and the runbook it maintains about this service."
        />
      </header>

      {/* ── availability + counters ──────────────────────────── */}
      {memory.initial ? (
        <Panel>
          <Loading label="Reading Hindsight" rows={4} />
        </Panel>
      ) : memory.error ? (
        <Failure
          title="Could not read memory"
          message={memory.error.message}
          detail={memory.error.detail}
          onRetry={memory.reload}
        />
      ) : !available ? (
        <Failure
          warning
          title="Hindsight unavailable"
          message="The memory service could not be reached, so the agent is running degraded: incidents are still investigated and verified, but nothing is recalled or learned."
          detail={memory.data?.detail}
          onRetry={memory.reload}
          retryLabel="Re-check"
        />
      ) : (
        <Panel>
          <div className="grid grid-cols-2 gap-px bg-hair lg:grid-cols-4">
            <Metric value={memory.data?.counters.retains ?? 0} label="Memories retained" />
            <Metric value={memory.data?.counters.recalls ?? 0} label="Recall operations" />
            <Metric value={memory.data?.counters.reflects ?? 0} label="Reflections" />
            <Metric
              value={memory.data?.counters.failures ?? 0}
              label="Failed operations"
              tone={(memory.data?.counters.failures ?? 0) > 0 ? 'warn' : 'ink'}
            />
          </div>
          <Rule />
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4">
            <div className="flex flex-wrap items-center gap-3">
              <Tag tone="neutral" title="Incident bank">
                <Database size={10} strokeWidth={3} aria-hidden />
                {memory.data?.banks?.incident?.bank_id}
              </Tag>
              <Tag tone="neutral" title="Convention bank">
                {memory.data?.banks?.conventions?.bank_id}
              </Tag>
              <Tag tone="ok">{status?.memory_defense || 'memory defense reported'}</Tag>
            </div>
            <Btn icon={RefreshCw} size="sm" variant="ghost" onClick={memory.reload}>
              Refresh
            </Btn>
          </div>
        </Panel>
      )}

      {/* ── search ───────────────────────────────────────────── */}
      <section>
        <SectionHeader
          index="02."
          title="Search memory"
          description="Runs the same tag-scoped retrieval the agent uses, so you can see exactly what it would find."
        />
        <Panel className="mt-5">
          <form
            className="flex flex-wrap items-center gap-3 border-b-2 border-ink px-4 py-3"
            onSubmit={(event) => {
              event.preventDefault()
              void runSearch()
            }}
          >
            <label className="relative flex min-w-[16rem] flex-1 items-center">
              <Search
                size={13}
                strokeWidth={2.5}
                className="pointer-events-none absolute left-3 text-status-idle"
                aria-hidden
              />
              <span className="sr-only">Search memories</span>
              <input
                className="swiss-input pl-9"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="e.g. connection pool exhausted"
                disabled={!available}
              />
            </label>
            <div className="flex items-center gap-1" role="group" aria-label="Bank">
              {(['incident', 'conventions'] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setBank(key)}
                  aria-pressed={bank === key}
                  className={`border-2 px-2.5 py-1.5 text-label font-bold uppercase tracking-wide transition-colors duration-150 ease-linear ${
                    bank === key
                      ? 'border-ink bg-ink text-paper'
                      : 'border-hair-strong text-status-idle hover:border-ink hover:text-ink'
                  }`}
                >
                  {key}
                </button>
              ))}
            </div>
            <Btn type="submit" icon={Search} disabled={searching || !available}>
              {searching ? 'Searching' : 'Search'}
            </Btn>
          </form>

          <div className="p-4">
            {!available ? (
              <p className="text-meta text-status-idle">Search is unavailable while Hindsight is unreachable.</p>
            ) : searchNote ? (
              <p className="text-meta text-status-idle">{searchNote}</p>
            ) : results === null ? (
              <p className="text-meta text-status-idle">
                Results appear here. The agent scores each memory, and the strongest matches are what it
                reasons over.
              </p>
            ) : (
              <div className="space-y-5">
                {results.map((memoryRef) => (
                  <MemoryCard key={memoryRef.memory_id} memory={memoryRef} />
                ))}
              </div>
            )}
          </div>
        </Panel>
      </section>

      {/* ── banks ────────────────────────────────────────────── */}
      <section>
        <SectionHeader
          index="03."
          title="Incident memory"
          description="Past failures for this service: symptom, root cause, every repair attempted, and the verified outcome."
          action={<Tag tone="neutral">{incidentMemories.length} entries</Tag>}
        />
        <div className="mt-5">
          {incidentBankError ? (
            <Failure
              warning
              title="The incident bank could not be read"
              message={incidentBankError}
              onRetry={memory.reload}
            />
          ) : incidentMemories.length === 0 ? (
            <Panel>
              <Empty
                icon={BrainCircuit}
                title="No historical memories"
                detail="Hindsight has not recorded any resolved incidents for this service yet. The first run will start from zero and teach it."
              />
            </Panel>
          ) : (
            <div className="space-y-5">
              {incidentMemories.slice(0, 25).map((memoryRef) => (
                <MemoryCard key={memoryRef.memory_id} memory={memoryRef} />
              ))}
            </div>
          )}
        </div>
      </section>

      <section>
        <SectionHeader
          index="04."
          title="Repository conventions"
          description="The rules the review gate checks generated patches against — including approaches previously rejected, so the agent stops proposing them."
          action={<Tag tone="neutral">{conventionMemories.length} entries</Tag>}
        />
        <div className="mt-5 grid gap-8 lg:grid-cols-2">
          <Panel>
            <div className="border-b-2 border-ink px-5 py-3 text-label font-black uppercase tracking-widest text-status-idle">
              Seeded conventions
            </div>
            {conventions.initial ? (
              <Loading label="Reading conventions" rows={3} />
            ) : (conventions.data?.conventions ?? []).length === 0 ? (
              <Empty
                icon={Database}
                title="No conventions configured"
                detail="config/conventions.py is empty or missing, so the review gate only applies its deterministic policy checks."
              />
            ) : (
              <ul className="divide-y divide-hair">
                {(conventions.data?.conventions ?? []).map((item, index) => (
                  <li key={index} className="flex items-start gap-3 px-5 py-3">
                    <span className="pt-1 font-mono text-micro text-accent">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span className="text-meta">{item}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel>
            <div className="flex items-center justify-between border-b-2 border-ink px-5 py-3">
              <span className="text-label font-black uppercase tracking-widest text-status-idle">
                Stored in the convention bank
              </span>
              {conventionMemories.length > 0 ? (
                <span className="font-mono text-micro text-status-idle">{conventionMemories.length}</span>
              ) : null}
            </div>
            {conventionMemories.length === 0 ? (
              <Empty
                icon={Database}
                title="Nothing retained yet"
                detail="Conventions are written to Hindsight when the agent starts up with seeding enabled, or when it records a rejected approach."
              />
            ) : (
              <div className="space-y-5 p-5">
                {conventionMemories.slice(0, 12).map((memoryRef) => (
                  <MemoryCard key={memoryRef.memory_id} memory={memoryRef} compact />
                ))}
              </div>
            )}
          </Panel>
        </div>
      </section>

      {/* ── runbook ──────────────────────────────────────────── */}
      <section>
        <SectionHeader
          index="05."
          title="Service runbook"
          description="A standing answer to “what are this service's recurring failure modes and which fixes actually worked?”. Hindsight rewrites it as the bank learns more."
        />
        <Panel className="mt-5">
          {runbook.initial ? (
            <Loading label="Reading the runbook" rows={4} />
          ) : runbook.error ? (
            <Failure
              title="Could not read the runbook"
              message={runbook.error.message}
              detail={runbook.error.detail}
              onRetry={runbook.reload}
            />
          ) : !runbook.data?.available ? (
            <Failure
              warning
              title="Runbook unavailable"
              message={runbook.data?.detail ?? 'Hindsight did not return the runbook.'}
              onRetry={runbook.reload}
            />
          ) : !runbook.data.content ? (
            <Empty
              icon={BrainCircuit}
              title="The runbook has not been written yet"
              detail="Hindsight generates it in the background from the incident bank. It stays empty until the bank holds enough evidence — a page of settled knowledge cannot exist before there is anything to settle."
            />
          ) : (
            <div>
              <div className="flex items-center justify-between gap-3 border-b-2 border-ink px-5 py-3">
                <span className="font-mono text-micro text-status-idle">{runbook.data.path}</span>
                <span className="font-mono text-micro text-status-idle">
                  {localDateTime(new Date().toISOString())}
                </span>
              </div>
              <pre className="whitespace-pre-wrap p-5 text-meta">{runbook.data.content}</pre>
            </div>
          )}
        </Panel>
      </section>
    </Page>
  )
}
