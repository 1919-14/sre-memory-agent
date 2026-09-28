import { BrainCircuit } from 'lucide-react'

import type { MemoryRef } from '../lib/api'
import { localDateTime, titleize } from '../lib/format'
import { Bar, Tag } from './primitives'

interface Against {
  error_class?: string | null
  repository?: string | null
}

/**
 * One recalled memory.
 *
 * Every "why relevant" line is derived from a field that actually exists on the memory
 * (its tags, metadata and scores). Nothing here is inferred or narrated, so a reviewer can
 * check each claim against the payload.
 */
export function MemoryCard({
  memory,
  against,
  compact = false,
}: {
  memory: MemoryRef
  against?: Against
  compact?: boolean
}) {
  const metadata = memory.metadata ?? {}
  const memoryClass = metadata.error_class
  const memoryRepo = metadata.repository
  const outcome = metadata.outcome

  const evidence: { ok: boolean; label: string }[] = []
  if (against?.error_class && memoryClass) {
    evidence.push({
      ok: memoryClass === against.error_class,
      label:
        memoryClass === against.error_class
          ? `Same error class (${memoryClass})`
          : `Different error class (${memoryClass})`,
    })
  }
  if (against?.repository && memoryRepo) {
    evidence.push({
      ok: memoryRepo === against.repository,
      label:
        memoryRepo === against.repository
          ? `Same repository (${memoryRepo})`
          : `Different repository (${memoryRepo})`,
    })
  }
  if (outcome) {
    evidence.push({
      ok: outcome === 'recovered',
      label:
        outcome === 'recovered'
          ? 'The previous repair succeeded'
          : `The previous incident ended ${outcome}`,
    })
  }

  return (
    <article className="border-2 border-hair-strong bg-paper">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-hair px-4 py-2">
        <div className="flex items-center gap-2">
          <BrainCircuit size={13} strokeWidth={2.5} className="text-status-idle" aria-hidden />
          <Tag tone="neutral">{memory.kind}</Tag>
          {memory.document_id ? <Tag tone="accent">{memory.document_id}</Tag> : null}
        </div>
        <div className="flex items-center gap-3">
          {memory.relevance !== null ? (
            // A Hindsight retrieval score, not a share of anything: it can legitimately exceed
            // 1.00, so presenting it as a percentage would invent a bound the score does not have.
            <span
              className="font-mono text-micro text-status-idle"
              title="Retrieval score — higher is closer to the query"
            >
              score {memory.relevance.toFixed(2)}
            </span>
          ) : null}
        </div>
      </header>

      <div className="px-4 py-3">
        <p className={`text-meta text-ink ${compact ? 'line-clamp-3' : ''}`}>{memory.text}</p>

        {memory.relevance !== null && !compact ? (
          <div className="mt-3 max-w-xs">
            <Bar
              value={memory.relevance}
              max={Math.max(1, memory.relevance)}
              label="Retrieval score — higher is closer to the query"
            />
          </div>
        ) : null}

        {evidence.length > 0 ? (
          <div className="mt-4">
            <div className="text-label font-black uppercase tracking-widest text-status-idle">
              Why this memory was considered
            </div>
            <ul className="mt-2 space-y-1">
              {evidence.map((item) => (
                <li key={item.label} className="flex items-center gap-2 text-micro">
                  <span
                    aria-hidden
                    className={`inline-block h-1.5 w-1.5 ${item.ok ? 'bg-status-ok' : 'bg-status-warn'}`}
                  />
                  <span className={item.ok ? 'text-ink' : 'text-status-idle'}>{item.label}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {!compact ? (
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 border-t-2 border-hair pt-3 text-micro">
            {metadata.incident_id ? (
              <Row k="Incident" v={metadata.incident_id} />
            ) : null}
            {metadata.attempts ? <Row k="Attempts" v={metadata.attempts} /> : null}
            {metadata.commit ? <Row k="Commit" v={metadata.commit.slice(0, 8)} /> : null}
            {metadata.run_mode ? <Row k="Run mode" v={metadata.run_mode} /> : null}
            {memory.mentioned_at ? <Row k="Recorded" v={localDateTime(memory.mentioned_at)} /> : null}
            {memory.retrieved_for ? <Row k="Retrieved for" v={titleize(memory.retrieved_for)} /> : null}
          </dl>
        ) : null}

        {memory.influence ? (
          <p className="mt-3 border-l-2 border-accent pl-3 text-micro text-status-idle">
            {memory.influence}
          </p>
        ) : null}

        {memory.tags.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {memory.tags.map((tag) => (
              <Tag key={tag} tone="neutral">
                {tag}
              </Tag>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-status-idle">{k}</dt>
      <dd className="truncate font-mono text-ink" title={v}>
        {v}
      </dd>
    </div>
  )
}
